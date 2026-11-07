// A Godot game package (.pck) made on the phone from a project's files, so
// Godot's web player can run a project without the editor. The layout is
// Godot 4.7's own (core/io/file_access_pack.cpp, format 4): a header, the
// files, then the directory of paths, offsets and sizes. Text files go in as
// they are; Godot loads scripts, scenes, shaders and resources from text.
// Pictures go in twice: as they are (for Image.load_from_file) and imported
// the way Godot's editor would (importPictures), so preload("res://x.png")
// and textures in scenes work on the phone too.

const MAGIC = 0x43504447; // "GDPC"
const FORMAT = 4;
const VERSION = [4, 7, 2];
const RELATIVE_FILE_BASE = 1 << 1;
const HEADER = 4 * 6 + 8 + 8 + 4 * 16;

const pad4 = (length) => (4 - (length % 4)) % 4;

/** The bytes of a file: text as UTF-8, data addresses decoded, bytes as is. */
export function fileBytes(body) {
  if (body instanceof Uint8Array) return body;
  if (body instanceof ArrayBuffer) return new Uint8Array(body);
  const text = String(body);
  const data = text.match(/^data:[^;,]*;base64,(.*)$/s);
  if (data) return Uint8Array.from(atob(data[1]), (char) => char.charCodeAt(0));
  return new TextEncoder().encode(text);
}

/** Pack files ({ "main.gd": text, ... }) into a .pck Godot's player opens;
 * `extra` holds ready bytes (the imported pictures) by path. */
export function makePack(files, extra = {}) {
  // The project's own .godot/ (an editor's cache), builds and screenshots stay
  // out; the imported pictures (extra) go in.
  const own = Object.entries(files).filter(([path]) => !path.startsWith(".godot/") && !path.startsWith("build/") && !path.startsWith("screenshots/"));
  const entries = [...own, ...Object.entries(extra)].map(([path, body]) => ({ path: `res://${path.replace(/^\/+/, "")}`, bytes: fileBytes(body) }));
  if (!entries.some((entry) => entry.path === "res://project.godot")) throw new Error("A Godot project needs a project.godot file.");
  // The class list the editor would have made (none: FCC's games preload
  // scripts by path), so Godot doesn't complain that it's missing.
  entries.push({ path: "res://.godot/global_script_class_cache.cfg", bytes: new TextEncoder().encode("list=[]\n") });
  const encoder = new TextEncoder();
  let dataSize = 0;
  for (const entry of entries) {
    entry.offset = dataSize;
    dataSize += entry.bytes.length + pad4(entry.bytes.length);
    entry.name = encoder.encode(entry.path);
  }
  const directorySize = 4 + entries.reduce((total, entry) => total + 4 + entry.name.length + pad4(entry.name.length) + 8 + 8 + 16 + 4, 0);
  const buffer = new ArrayBuffer(HEADER + dataSize + directorySize);
  const view = new DataView(buffer);
  const bytes = new Uint8Array(buffer);
  let at = 0;
  const u32 = (value) => {
    view.setUint32(at, value, true);
    at += 4;
  };
  const u64 = (value) => {
    view.setBigUint64(at, BigInt(value), true);
    at += 8;
  };
  u32(MAGIC);
  u32(FORMAT);
  for (const part of VERSION) u32(part);
  u32(RELATIVE_FILE_BASE);
  u64(HEADER); // where the files start (from the start of the pack)
  u64(HEADER + dataSize); // where the directory starts
  for (let i = 0; i < 16; i += 1) u32(0); // reserved
  for (const entry of entries) {
    bytes.set(entry.bytes, HEADER + entry.offset);
  }
  at = HEADER + dataSize;
  u32(entries.length);
  for (const entry of entries) {
    u32(entry.name.length + pad4(entry.name.length));
    bytes.set(entry.name, at);
    at += entry.name.length + pad4(entry.name.length);
    u64(entry.offset);
    u64(entry.bytes.length);
    at += 16; // MD5 (left blank; Godot doesn't check it when loading)
    u32(0); // flags
  }
  return buffer;
}

/** True when a project is a Godot game (it has project.godot). */
export const isGodotProject = (project) => Boolean(project && project.files && typeof project.files["project.godot"] === "string");

const PICTURE = /\.(png|jpe?g|webp|gif|bmp)$/i;
const FORMAT_RGBA8 = 5;

/** A short, stable name for an imported file (like the editor's md5 suffix). */
function stamp(text) {
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i += 1) hash = Math.imul(hash ^ text.charCodeAt(i), 0x01000193) >>> 0;
  return hash.toString(16).padStart(8, "0");
}

/** PNG bytes for a picture: PNGs as they are, others drawn into a PNG. */
async function asPng(bytes, path) {
  if (bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47) return bytes;
  const bitmap = await createImageBitmap(new Blob([bytes]));
  const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
  canvas.getContext("2d").drawImage(bitmap, 0, 0);
  bitmap.close();
  const blob = await canvas.convertToBlob({ type: "image/png" });
  if (!blob) throw new Error(`${path}: couldn't turn it into a PNG for Godot.`);
  return new Uint8Array(await blob.arrayBuffer());
}

/** A Godot 4 compressed texture (.ctex, format 1) holding one PNG, as the
 * editor writes it (editor/import/resource_importer_texture.cpp). */
export function ctexFromPng(png) {
  const width = new DataView(png.buffer, png.byteOffset).getUint32(16);
  const height = new DataView(png.buffer, png.byteOffset).getUint32(20);
  // "GST2", 8 header words, the image header (4 + 2 + 2 + 4 + 4), the size,
  // then "PNG " and the PNG (Godot's PNG reader expects that tag first).
  const out = new Uint8Array(4 + 8 * 4 + 16 + 4 + 4 + png.length);
  const view = new DataView(out.buffer);
  out.set([0x47, 0x53, 0x54, 0x32]); // "GST2"
  let at = 4;
  const u32 = (value) => {
    view.setUint32(at, value >>> 0, true);
    at += 4;
  };
  const u16 = (value) => {
    view.setUint16(at, value, true);
    at += 2;
  };
  u32(1); // format version
  u32(width);
  u32(height);
  u32(0); // flags: not streamed, no mipmaps
  u32(0xffffffff); // mipmap limit: none
  u32(0);
  u32(0);
  u32(0);
  u32(1); // DATA_FORMAT_PNG
  u16(width);
  u16(height);
  u32(0); // mipmaps
  u32(FORMAT_RGBA8); // Godot converts the PNG to this as it loads
  u32(png.length + 4);
  out.set([0x50, 0x4e, 0x47, 0x20], at); // "PNG "
  out.set(png, at + 4);
  return { bytes: out, width, height };
}

/** The imported copies of every picture: { "x.png.import": text, ".godot/imported/...ctex": bytes }. */
export async function importPictures(files) {
  const out = {};
  for (const [path, body] of Object.entries(files)) {
    if (!PICTURE.test(path) || path.startsWith(".godot/") || path.startsWith("parts/")) continue;
    const png = await asPng(fileBytes(body), path);
    const name = `${path.split("/").pop()}-${stamp(path)}.ctex`;
    out[`.godot/imported/${name}`] = ctexFromPng(png).bytes;
    out[`${path}.import`] = new TextEncoder().encode(`[remap]\n\nimporter="texture"\ntype="CompressedTexture2D"\npath="res://.godot/imported/${name}"\nmetadata={\n"vram_texture": false\n}\n`);
  }
  return out;
}
