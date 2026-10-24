// Read what a GGUF model file says about itself, without loading it: the same
// facts Model Control on the PC shows (size, context, layers, tools, reasoning).

const TOOL_WORD = /\btools\b/;
const TOOL_FORMAT = /tool_call|tool_response|TOOL_CALLS|TOOL_RESULTS|python_tag|ipython|<function|\bfunction\b|tool▁call/i;
const THINKING = /<think>|enable_thinking|reasoning_content|reasoning_effort|<\|channel\|>analysis/i;
const REASONING_NAME = /(?:^|[-_ ./])(?:r1|qwq|reasoning|reasoner|thinking|magistral|gpt-oss|qwen3)(?:$|[-_ .])/i;
const FIXED = { 0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8 };
const CHUNK = 4 * 1024 * 1024;

export const supportsTools = (template) => TOOL_WORD.test(template) && TOOL_FORMAT.test(template);
export const thinks = (template, name) => THINKING.test(template) || REASONING_NAME.test(name);

class Reader {
  constructor(blob) {
    this.blob = blob;
    this.pos = 0;
    this.base = 0;
    this.view = new DataView(new ArrayBuffer(0));
  }
  async need(count) {
    const end = this.pos + count;
    if (this.pos >= this.base && end <= this.base + this.view.byteLength) return;
    if (end > this.blob.size) throw new Error("the file ended early");
    const buffer = await this.blob.slice(this.pos, Math.min(this.blob.size, this.pos + Math.max(CHUNK, count))).arrayBuffer();
    this.base = this.pos;
    this.view = new DataView(buffer);
  }
  async u32() {
    await this.need(4);
    const value = this.view.getUint32(this.pos - this.base, true);
    this.pos += 4;
    return value;
  }
  async u64() {
    await this.need(8);
    const value = Number(this.view.getBigUint64(this.pos - this.base, true));
    this.pos += 8;
    return value;
  }
  async string() {
    const length = await this.u64();
    if (length > 1 << 24) throw new Error("a header string is too long");
    await this.need(length);
    const text = new TextDecoder().decode(new Uint8Array(this.view.buffer, this.pos - this.base, length));
    this.pos += length;
    return text;
  }
  async scalar(kind) {
    const size = FIXED[kind];
    await this.need(size);
    const at = this.pos - this.base;
    const view = this.view;
    const value =
      kind === 0 ? view.getUint8(at)
      : kind === 1 ? view.getInt8(at)
      : kind === 2 ? view.getUint16(at, true)
      : kind === 3 ? view.getInt16(at, true)
      : kind === 4 ? view.getUint32(at, true)
      : kind === 5 ? view.getInt32(at, true)
      : kind === 6 ? view.getFloat32(at, true)
      : kind === 7 ? view.getUint8(at) !== 0
      : kind === 10 ? Number(view.getBigUint64(at, true))
      : kind === 11 ? Number(view.getBigInt64(at, true))
      : view.getFloat64(at, true);
    this.pos += size;
    return value;
  }
  async value(kind, keep) {
    if (kind === 8) return this.string();
    if (kind === 9) {
      const inner = await this.u32();
      const count = await this.u64();
      if (inner in FIXED && !keep) {
        this.pos += FIXED[inner] * count;
        return null;
      }
      const items = [];
      for (let i = 0; i < count; i += 1) {
        const item = await this.value(inner, keep);
        if (keep) items.push(item);
      }
      return keep ? items : null;
    }
    if (kind in FIXED) return this.scalar(kind);
    throw new Error(`unknown value type ${kind}`);
  }
}

/** The facts in a GGUF file's header, or throws if it isn't a GGUF model. */
export async function readGguf(blob, fileName = "") {
  const reader = new Reader(blob);
  await reader.need(24);
  const magic = new TextDecoder().decode(new Uint8Array(reader.view.buffer, 0, 4));
  if (magic !== "GGUF") throw new Error("This isn't a GGUF model file.");
  reader.pos = 4;
  const version = await reader.u32();
  if (version < 2) throw new Error("This GGUF file is too old to read.");
  await reader.u64(); // tensors
  const count = await reader.u64();
  const values = {};
  for (let i = 0; i < count; i += 1) {
    const key = await reader.string();
    const kind = await reader.u32();
    const keep = key.startsWith("general.") || key === "tokenizer.chat_template" || /\.(context_length|block_count|embedding_length|attention\.head_count|attention\.head_count_kv)$/.test(key);
    const value = await reader.value(kind, keep);
    if (keep) values[key] = value;
  }
  const arch = values["general.architecture"] || "";
  const number = (name) => Number(values[`${arch}.${name}`]) || 0;
  const template = values["tokenizer.chat_template"] || "";
  const name = `${values["general.name"] || ""} ${fileName}`;
  return {
    architecture: arch,
    name: values["general.name"] || "",
    sizeLabel: values["general.size_label"] || "",
    contextMax: number("context_length"),
    layers: number("block_count"),
    embedding: number("embedding_length"),
    heads: number("attention.head_count"),
    kvHeads: number("attention.head_count_kv"),
    tools: supportsTools(template),
    reasoning: thinks(template, name),
    hasTemplate: Boolean(template),
  };
}

/** About how much memory a model needs at a context size, in bytes. */
export function estimateMemory(info, fileSize, context) {
  const layers = info.layers || 24;
  const heads = info.heads || 16;
  const headSize = info.embedding ? info.embedding / heads : 64;
  const kvHeads = info.kvHeads || heads;
  const kv = layers * context * kvHeads * headSize * 2 * 2;
  return fileSize + kv + 150 * 1024 * 1024;
}
