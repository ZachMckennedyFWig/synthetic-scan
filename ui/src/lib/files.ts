/**
 * Turning a drop (or a file/folder picker) into a flat list of accepted parts.
 *
 * Folders are the common case -- people drop a whole CAD export directory --
 * and `DataTransfer.files` only lists the top-level items, with folders showing
 * up as zero-byte "files". So drops go through `webkitGetAsEntry()` and recurse.
 */

/** Accepted formats per docs/API.md. STEP only when the backend has OCC. */
const MESH_EXTS = ['.stl', '.obj', '.ply', '.3mf', '.glb', '.off']
const STEP_EXTS = ['.step', '.stp']

export function acceptedExtensions(stepSupport: boolean): string[] {
  return stepSupport ? [...STEP_EXTS, ...MESH_EXTS] : MESH_EXTS
}

export function extOf(name: string): string {
  const i = name.lastIndexOf('.')
  return i < 0 ? '' : name.slice(i).toLowerCase()
}

export interface Collected {
  files: File[]
  /** Files that were found but have an extension the backend will not take. */
  rejected: string[]
}

function readAllEntries(reader: FileSystemDirectoryReader): Promise<FileSystemEntry[]> {
  // readEntries returns at most ~100 entries per call (Chrome); keep calling
  // until it hands back an empty batch.
  return new Promise((resolve, reject) => {
    const out: FileSystemEntry[] = []
    const next = () =>
      reader.readEntries((batch) => {
        if (batch.length === 0) resolve(out)
        else {
          out.push(...batch)
          next()
        }
      }, reject)
    next()
  })
}

function fileOf(entry: FileSystemFileEntry): Promise<File> {
  return new Promise((resolve, reject) => entry.file(resolve, reject))
}

async function walk(entry: FileSystemEntry, accept: Set<string>, out: Collected): Promise<void> {
  if (entry.name.startsWith('.')) return // .DS_Store, .git, editor droppings
  if (entry.isFile) {
    if (accept.has(extOf(entry.name))) out.files.push(await fileOf(entry as FileSystemFileEntry))
    else out.rejected.push(entry.name)
    return
  }
  if (entry.isDirectory) {
    const children = await readAllEntries((entry as FileSystemDirectoryEntry).createReader())
    for (const child of children) await walk(child, accept, out)
  }
}

/**
 * Must be called synchronously from the drop handler: the DataTransfer's items
 * are neutered as soon as the event returns, so the entries are grabbed first
 * and only the traversal is async.
 */
export function collectDrop(dt: DataTransfer, exts: string[]): Promise<Collected> {
  const accept = new Set(exts)
  const entries: FileSystemEntry[] = []
  const loose: File[] = []
  for (const item of Array.from(dt.items)) {
    if (item.kind !== 'file') continue
    const entry = item.webkitGetAsEntry?.()
    if (entry) entries.push(entry)
    else {
      const f = item.getAsFile()
      if (f) loose.push(f)
    }
  }
  return (async () => {
    const out: Collected = { files: [], rejected: [] }
    for (const entry of entries) await walk(entry, accept, out)
    for (const f of loose) {
      if (accept.has(extOf(f.name))) out.files.push(f)
      else out.rejected.push(f.name)
    }
    return out
  })()
}

/** Same filter for <input type=file> (including webkitdirectory pickers). */
export function collectFileList(list: FileList | null, exts: string[]): Collected {
  const accept = new Set(exts)
  const out: Collected = { files: [], rejected: [] }
  for (const f of Array.from(list ?? [])) {
    if (f.name.startsWith('.')) continue
    if (accept.has(extOf(f.name))) out.files.push(f)
    else out.rejected.push(f.name)
  }
  return out
}
