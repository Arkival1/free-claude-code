// A Godot game package (.pck) made on the phone from a project's files, so
// Godot's web player can run a project without the editor. The layout is
// Godot 4.7's own (core/io/file_access_pack.cpp, format 4): a header, the
// files, then the directory of paths, offsets and sizes. Text files only go
// in as they are; Godot loads scripts, scenes, shaders and resources from
// text. Pictures and sounds the game loads itself at run time (Image.load_*).

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

/** Pack files ({ "main.gd": text, ... }) into a .pck Godot's player opens. */
export function makePack(files) {
  const entries = Object.entries(files)
    .filter(([path]) => !path.startsWith(".godot/") && !path.startsWith("build/") && !path.startsWith("screenshots/"))
    .map(([path, body]) => ({ path: `res://${path.replace(/^\/+/, "")}`, bytes: fileBytes(body) }));
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
