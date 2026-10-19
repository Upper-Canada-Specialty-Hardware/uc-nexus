import { useRef } from 'react';
import { Button, CircularProgress, IconButton, Tooltip } from '@mui/material';
import { useApolloClient, useMutation } from '@apollo/client/react';
import { Camera } from 'lucide-react';
import { ADD_SHIPMENT_PHOTO } from '../../graphql/shipping';
import { userMessage } from '../../graphql/userMessage';
import { useToast } from '../../components/Toast';
import { fileToBase64, MAX_PHOTO_BYTES } from './photos';

/** The file's type, or one read off its extension when the browser gave none - never a guess. An unknown
 *  one is sent as it is and the server says which photos it takes. */
function photoType(file: File): string {
  if (file.type) return file.type;
  const ext = file.name.split('.').pop()?.toLowerCase();
  return ext === 'jpg' || ext === 'jpeg' ? 'image/jpeg' : ext === 'png' ? 'image/png' : ext === 'webp' ? 'image/webp' : '';
}

interface Props {
  kind: 'LOADING' | 'DELIVERY';
  containerId?: string;
  packingSlipId?: string;
  /** Operation names to refetch once the photo is stored, so the strip showing it updates. */
  refetchQueries: string[];
  /** A full-width labelled button (the driver's phone) rather than an icon (a container's header). */
  label?: string;
  disabled?: boolean;
}

/**
 * Take a photo (#1728). On a phone the file input opens the rear camera straight away
 * (`capture="environment"`); on a desktop it is an ordinary file picker. Several at once are fine - a
 * driver photographs a load from more than one side.
 */
export default function PhotoCapture({ kind, containerId, packingSlipId, refetchQueries, label, disabled }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const { showToast } = useToast();
  const client = useApolloClient();
  const [addPhoto, { loading }] = useMutation(ADD_SHIPMENT_PHOTO);

  const upload = async (files: FileList | null) => {
    let added = 0;
    for (const file of Array.from(files ?? [])) {
      if (file.size > MAX_PHOTO_BYTES) {
        showToast(`${file.name} is larger than ${MAX_PHOTO_BYTES / (1024 * 1024)} MB`, 'error');
        continue;
      }
      try {
        await addPhoto({
          variables: {
            kind,
            containerId: containerId ?? null,
            packingSlipId: packingSlipId ?? null,
            fileName: file.name,
            contentType: photoType(file),
            fileDataBase64: await fileToBase64(file),
          },
        });
        added += 1;
      } catch (e) {
        showToast(userMessage(e), 'error');
        break;
      }
    }
    if (input.current) input.current.value = '';
    // Once for the batch, not once per photo: a driver adding six photos over a cab's signal should not
    // read the whole list back six times.
    if (added > 0 && refetchQueries.length > 0) void client.refetchQueries({ include: refetchQueries });
  };

  const busy = disabled || loading;
  const hidden = (
    <input
      ref={input}
      type="file"
      // The three types every office browser shows. Listing them (not image/*) is also what makes an
      // iPhone hand a HEIC photo from its library over as a JPEG.
      accept="image/jpeg,image/png,image/webp"
      capture="environment"
      multiple
      hidden
      onChange={(e) => void upload(e.target.files)}
      data-testid={`photo-input-${kind.toLowerCase()}`}
    />
  );

  if (label) {
    return (
      <>
        {hidden}
        <Button
          variant="outlined"
          fullWidth
          disabled={busy}
          startIcon={loading ? <CircularProgress size={16} /> : <Camera size={18} strokeWidth={1.75} />}
          onClick={() => input.current?.click()}
        >
          {loading ? 'Saving photo...' : label}
        </Button>
      </>
    );
  }
  return (
    <>
      {hidden}
      <Tooltip title="Add a photo">
        <span>
          <IconButton size="small" aria-label="Add a photo" disabled={busy} onClick={() => input.current?.click()}>
            {loading ? <CircularProgress size={14} /> : <Camera size={16} strokeWidth={1.75} />}
          </IconButton>
        </span>
      </Tooltip>
    </>
  );
}
