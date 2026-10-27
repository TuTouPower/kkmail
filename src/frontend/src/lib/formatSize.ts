/**
 * Format byte count into human-readable file size string.
 * Examples: 0 B, 512 B, 1.5 KB, 20.4 MB, 1.2 GB.
 */
export function formatFileSize(bytes?: number | null): string {
  // A334: reject non-finite sizes (Infinity used to render "Infinity TB").
  if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return ''
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const k = 1024
  const i = Math.max(0, Math.min(Math.floor(Math.log(bytes) / Math.log(k)), units.length - 1))
  // Byte counts are integral; floor fractional input in the B tier.
  if (i === 0) return `${Math.floor(bytes)} B`
  const val = bytes / Math.pow(k, i)
  const formatted = val.toFixed(1).replace(/\.0$/, '')
  return `${formatted} ${units[i]}`
}
