import { Box, IconButton, Tooltip } from '@mui/material';
import { useMutation } from '@apollo/client/react';
import { X } from 'lucide-react';
import { DELETE_SHIPMENT_PHOTO } from '../../graphql/shipping';
import { userMessage } from '../../graphql/userMessage';
import { useToast } from '../../components/Toast';
import { parseServerDate } from '../../utils/serverDate';
import type { ShipmentPhoto } from './photos';

interface Props {
  photos: ShipmentPhoto[];
  /** Operation names to refetch once a photo is removed. Omitted, the strip is read-only. */
  removeRefetchQueries?: string[];
}

/**
 * A row of photo thumbnails (#1728) that wraps rather than scrolling sideways. Each opens full size in
 * a new tab; when removing is allowed, a photo taken by mistake can be taken back off.
 */
export default function PhotoStrip({ photos, removeRefetchQueries }: Props) {
  const { showToast } = useToast();
  const [remove] = useMutation(DELETE_SHIPMENT_PHOTO, { refetchQueries: removeRefetchQueries ?? [] });
  if (photos.length === 0) return null;

  return (
    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75, minWidth: 0 }}>
      {photos.map((photo) => {
        const caption = `${photo.kind === 'DELIVERY' ? 'Delivery' : 'Loading'} photo by ${photo.takenBy}, ${parseServerDate(
          photo.takenAt,
        ).toLocaleString()}`;
        return (
          <Box key={photo.id} sx={{ position: 'relative', width: 72, height: 72, flexShrink: 0 }}>
            <Tooltip title={caption}>
              <Box
                component="a"
                href={photo.url}
                target="_blank"
                rel="noopener"
                aria-label={caption}
                sx={{ display: 'block', width: '100%', height: '100%', borderRadius: 1, overflow: 'hidden', border: 1, borderColor: 'divider' }}
              >
                <Box
                  component="img"
                  src={photo.url}
                  alt={caption}
                  loading="lazy"
                  sx={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
                />
              </Box>
            </Tooltip>
            {removeRefetchQueries && (
              <IconButton
                size="small"
                aria-label={`Remove ${caption}`}
                onClick={() =>
                  void remove({ variables: { id: photo.id } }).catch((e) => showToast(userMessage(e), 'error'))
                }
                sx={{ position: 'absolute', top: 2, right: 2, p: 0.25, bgcolor: 'background.paper', '&:hover': { bgcolor: 'background.paper' } }}
              >
                <X size={12} strokeWidth={2} />
              </IconButton>
            )}
          </Box>
        );
      })}
    </Box>
  );
}
