/** A photo of a container as loaded, or of a load as delivered (#1728). */
export interface ShipmentPhoto {
  id: string;
  kind: 'LOADING' | 'DELIVERY';
  containerId: string | null;
  packingSlipId: string | null;
  fileName: string;
  takenBy: string;
  takenByUserId: string | null;
  takenAt: string;
  /** Signed when read, good for an hour. */
  url: string;
}

/** The server's cap, said here too so a phone does not read and send a file it will refuse. */
export const MAX_PHOTO_BYTES = 15 * 1024 * 1024;

/** The mutation takes the raw base64 payload, so the data: URL prefix the reader adds is stripped. */
export function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1] ?? '');
    reader.onerror = () => reject(new Error(`Could not read ${file.name}`));
    reader.readAsDataURL(file);
  });
}
