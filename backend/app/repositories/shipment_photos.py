"""Shipment photos (#1728): containers as loaded, loads as delivered.

Stored the way PO documents are - the image in object storage, the row pointing at it - with two
differences: only images are taken, and a photo is of something physical, so it hangs off the
container or slip it shows rather than off a document list.
"""

import base64
import binascii
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import InvalidStateTransitionError, NotFoundError, ValidationError
from app.models.enums import ShipmentPhotoKind, ShipmentStatus
from app.models.shipment_container import ShipmentContainer
from app.models.shipment_photo import ShipmentPhoto
from app.models.shipping import PackingSlip
from app.repositories.po_repository import _safe_key_name
from app.status_labels import REFRESH_HINT

logger = logging.getLogger(__name__)

# A phone photo is a few megabytes; this leaves room for a large one without letting a video through.
MAX_PHOTO_BYTES = 15 * 1024 * 1024

# What every browser in the office can show. HEIC (an iPhone's own format) is left out: Chrome and Firefox
# on a desktop cannot render it, so a delivery photo stored as HEIC is a broken thumbnail for everybody
# but the driver. An iPhone's camera, opened from the page, hands over a JPEG anyway.
_PHOTO_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})


def _decode(file_data_base64: str) -> bytes:
    """The upload's bytes, refused before decoding when the encoded length is already over the cap."""
    if len(file_data_base64 or "") > (MAX_PHOTO_BYTES * 4) // 3 + 4:
        raise ValidationError(f"The photo is larger than {MAX_PHOTO_BYTES // (1024 * 1024)} MB", field="file")
    try:
        data = base64.b64decode(file_data_base64 or "", validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValidationError("The photo could not be read; take it again", field="file") from e
    if not data:
        raise ValidationError("The photo is empty", field="file")
    if len(data) > MAX_PHOTO_BYTES:
        raise ValidationError(f"The photo is larger than {MAX_PHOTO_BYTES // (1024 * 1024)} MB", field="file")
    return data


def _photo_type(content_type: str | None) -> str:
    normalised = (content_type or "").split(";", 1)[0].strip().lower()
    if normalised not in _PHOTO_TYPES:
        raise ValidationError(
            "Only JPEG, PNG or WebP photos can be added. An iPhone photo saved as HEIC: take it with the "
            "camera from this page instead, or share it as a JPEG.",
            field="file",
        )
    return normalised


def _subject(session: Session, kind: ShipmentPhotoKind, container_id, packing_slip_id):
    """The project, container and slip a photo is of, checked against what kind of photo it is.

    A loading photo is of a container; a delivery photo is of a slip that has left the dock. A delivery
    photo of a slip still on the dock, or a loading photo of a slip, is refused - each answers a
    different question, and a photo filed under the wrong one answers neither.
    """
    if kind == ShipmentPhotoKind.LOADING:
        if container_id is None or packing_slip_id is not None:
            raise ValidationError("A loading photo is of a container.", field="container_id")
        container = session.get(ShipmentContainer, container_id)
        if container is None:
            raise NotFoundError(f"Shipment container {container_id} not found")
        return container.project_id, container.id, container.packing_slip_id
    if packing_slip_id is None or container_id is not None:
        raise ValidationError("A delivery photo is of a shipment.", field="packing_slip_id")
    slip = session.get(PackingSlip, packing_slip_id)
    if slip is None:
        raise NotFoundError(f"Packing slip {packing_slip_id} not found")
    if slip.status not in (ShipmentStatus.PICKED_UP, ShipmentStatus.DELIVERED):
        raise InvalidStateTransitionError(
            f"Shipment {slip.packing_slip_number} has not left the dock yet; "
            f"a delivery photo is taken at the site. {REFRESH_HINT}"
        )
    return slip.project_id, None, slip.id


def add_photo(
    session: Session,
    *,
    kind: ShipmentPhotoKind,
    container_id: uuid.UUID | None,
    packing_slip_id: uuid.UUID | None,
    file_name: str,
    content_type: str,
    file_data_base64: str,
    taken_by: str,
    taken_by_user_id: str | None,
) -> ShipmentPhoto:
    """Store a photo and the row that finds it. The object is discarded if the row cannot be written."""
    from app.services import storage

    project_id, container_id, slip_id = _subject(session, kind, container_id, packing_slip_id)
    stored_type = _photo_type(content_type)
    data = _decode(file_data_base64)
    photo_id = uuid.uuid4()
    s3_key = f"shipment-photos/{project_id}/{photo_id}_{_safe_key_name(file_name)}"
    storage.upload_file(s3_key, data, stored_type)
    try:
        photo = ShipmentPhoto(
            id=photo_id,
            project_id=project_id,
            # A loading photo keeps its container even once the container has shipped, and the slip too,
            # so the slip's read finds it without going through the container.
            container_id=container_id,
            packing_slip_id=slip_id,
            kind=kind,
            s3_key=s3_key,
            file_name=(file_name or "photo").strip()[:200] or "photo",
            content_type=stored_type,
            file_size=len(data),
            taken_by=taken_by,
            taken_by_user_id=taken_by_user_id,
        )
        session.add(photo)
        session.flush()
    except Exception:
        discard_object(s3_key)
        raise
    return photo


def delete_photo(session: Session, photo_id: uuid.UUID) -> str:
    """Remove a photo taken by mistake, returning its storage key for the caller to delete after commit."""
    photo = session.get(ShipmentPhoto, photo_id)
    if photo is None:
        raise NotFoundError(f"Photo {photo_id} not found")
    key = photo.s3_key
    session.delete(photo)
    session.flush()
    return key


def container_photo_keys(session: Session, container_id: uuid.UUID) -> list[str]:
    """The storage keys of a container's photos, for deleting the objects when it is broken down."""
    return list(session.scalars(select(ShipmentPhoto.s3_key).where(ShipmentPhoto.container_id == container_id)))


def stamp_slip(session: Session, container_ids: list[uuid.UUID], packing_slip_id: uuid.UUID) -> None:
    """Put the containers' loading photos on the slip they shipped on, so the slip's read finds them."""
    for photo in session.scalars(select(ShipmentPhoto).where(ShipmentPhoto.container_id.in_(container_ids))):
        photo.packing_slip_id = packing_slip_id


def discard_object(s3_key: str) -> None:
    """Best effort: a failure here costs an orphaned object, and the error that got us here matters more."""
    from app.services import storage

    try:
        storage.delete_file(s3_key)
    except Exception:  # noqa: BLE001
        logger.warning("shipment photo not removed from storage", extra={"s3_key": s3_key}, exc_info=True)
