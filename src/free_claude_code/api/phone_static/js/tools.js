// The tools phone agents use, described once for every brain and run here.
import { state, save, feed, changed, toolsOf, agentByName } from "./state.js";
import { uid, words } from "./ui.js";
import { isPrivate } from "./brains.js";
import { syncSoon, pcSearch } from "./sync.js";
import * as projects from "./projects.js";
import { polishNotes } from "./polish.js";
import { lookAtSite, describeLook } from "./inspect.js";
import { TEMPLATES, templateFiles } from "./templates.js";

const hooks = { delegate: null, learn: null, teamStatus: null };
export function setHooks(next) {
  Object.assign(hooks, next);
}

const text = (description) => ({ type: "string", description });
export const SPECS = {
  remember: {
    description: "Save one fact worth keeping: something about the user, a plan, a preference, or a result. Shared by every agent on the phone (and with the PC when paired).",
    parameters: { type: "object", properties: { text: text("The fact, in one clear sentence.") }, required: ["text"] },
  },
  recall: {
    description: "Search memory for what is known about something before answering.",
    parameters: { type: "object", properties: { query: text("What to look for.") }, required: ["query"] },
  },
  calculate: {
    description: "Exact arithmetic: + - * / % ^, brackets, sqrt, round, min, max, '15% of 80'. Use it for every sum.",
    parameters: { type: "object", properties: { expression: text("The sum.") }, required: ["expression"] },
  },
  weather: {
    description: "The weather now and for the next days in any town or city.",
    parameters: { type: "object", properties: { place: text("Town or city."), days: { type: "integer", description: "1 to 7, default 3" } }, required: ["place"] },
  },
  wikipedia: {
    description: "Look up a fact, person, place, or topic on Wikipedia and read the summary.",
    parameters: { type: "object", properties: { query: text("What to look up.") }, required: ["query"] },
  },
  read_page: {
    description: "Read a web page as plain text, from its https:// address.",
    parameters: { type: "object", properties: { url: text("The page's address.") }, required: ["url"] },
  },
  web_search: {
    description: "Search the web (through the user's PC) and get titles, links, and snippets.",
    parameters: { type: "object", properties: { query: text("What to search for.") }, required: ["query"] },
  },
  todo: {
    description: "The user's to-do list and reminders. action 'add' with text (and optional due like 'in 20 minutes', 'tomorrow 9am', '17:30'), 'list', or 'done' with the item's text or id.",
    parameters: {
      type: "object",
      properties: { action: { type: "string", enum: ["add", "list", "done"] }, text: text("The to-do, or which one."), due: text("When to remind, if at all.") },
      required: ["action"],
    },
  },
  start_project: {
    description: `Start (or switch to) a project, a folder of files for a website or app. For a new one, pick the closest starter template (${Object.entries(TEMPLATES).map(([name, t]) => `${name}: ${t.about}`).join("; ")}), then make it the user's.`,
    parameters: {
      type: "object",
      properties: { name: text("The project's name."), template: { type: "string", enum: Object.keys(TEMPLATES), description: "A starter template for a new project." } },
      required: ["name"],
    },
  },
  write_file: {
    description: "Write one whole file in the current project (index.html, style.css, script.js, …). Always the complete file.",
    parameters: { type: "object", properties: { path: text("File name, like index.html."), content: text("The complete file.") }, required: ["path", "content"] },
  },
  read_file: {
    description: "Read one file of the current project.",
    parameters: { type: "object", properties: { path: text("File name.") }, required: ["path"] },
  },
  edit_file: {
    description: "Change part of a file: replace the exact text 'find' with 'replace'.",
    parameters: { type: "object", properties: { path: text("File name."), find: text("Exact text now in the file."), replace: text("What it becomes.") }, required: ["path", "find", "replace"] },
  },
  list_files: {
    description: "List the current project's files and their sizes.",
    parameters: { type: "object", properties: {} },
  },
  delete_file: {
    description: "Delete one file from the current project.",
    parameters: { type: "object", properties: { path: text("File name.") }, required: ["path"] },
  },
  restore_file: {
    description: "Undo changes to a file: put back an earlier version (1 = before the last change). Without versions_back, lists the saved versions.",
    parameters: { type: "object", properties: { path: text("File name."), versions_back: { type: "integer" } }, required: ["path"] },
  },
  find_images: {
    description: "Find real photos a website may use for free (Creative Commons, fine for business use), with sizes and credit lines. Use the https address straight in <img src>, with alt, width, and height, and put the credit in the footer.",
    parameters: {
      type: "object",
      properties: { query: text("What the photo shows, e.g. 'coffee shop interior'."), count: { type: "integer", description: "1 to 10, default 5" }, orientation: { type: "string", enum: ["wide", "tall", "square"] } },
      required: ["query"],
    },
  },
  polish_check: {
    description: "A designer's once-over of the pages: contrast, phone layout, fonts, hover and focus states, pictures, structure. Make the changes that fit.",
    parameters: { type: "object", properties: {} },
  },
  look_at_site: {
    description: "Open the site like a visitor, on a phone (390px) and a computer (1280px), and report what shows first and what's wrong: sideways scrolling, broken pictures, script errors, tiny text, hard-to-read colours, small buttons.",
    parameters: { type: "object", properties: {} },
  },
  check_project: {
    description: "Check the current project for problems: missing pages, broken links, placeholder text, missing viewport or titles.",
    parameters: { type: "object", properties: {} },
  },
  ask_agent: {
    description: "Hand a job to a teammate (Builder, Researcher, Helper, Tester, …) and get their report. Give a clear, complete task.",
    parameters: { type: "object", properties: { agent: text("The teammate's name."), task: text("What they should do."), project: text("A project name, for building work.") }, required: ["agent", "task"] },
  },
  team_status: {
    description: "What every agent is doing right now and what they last finished.",
    parameters: { type: "object", properties: {} },
  },
  learn: {
    description: "Start studying a subject: plans lessons, reads up on each, writes notes, and shows a progress bar.",
    parameters: { type: "object", properties: { topic: text("The subject."), depth: { type: "string", enum: ["quick", "normal", "deep"] } }, required: ["topic"] },
  },
};

export function specsFor(agent) {
  return toolsOf(agent)
    .filter((name) => SPECS[name])
    .map((name) => ({ type: "function", function: { name, description: SPECS[name].description, parameters: SPECS[name].parameters } }));
}

/** Run one tool call for an agent. ctx: {project, depth, chain}. Returns text. */
export async function runTool(agent, call, ctx) {
  const args = call.arguments || {};
  if (!toolsOf(agent).includes(call.name)) return `${agent.name} doesn't have the ${call.name} tool. Its tools: ${toolsOf(agent).join(", ")}.`;
  try {
    switch (call.name) {
      case "remember":
        return await remember(agent, String(args.text || ""));
      case "recall": {
        const found = recall(agent, String(args.query || ""), 8);
        return found.length ? found.map((row) => `- ${row.text}${row.from ? ` (${row.from})` : ""}`).join("\n") : "Nothing in memory about that.";
      }
      case "calculate":
        return `${args.expression} = ${formatNumber(calculate(String(args.expression || "")))}`;
      case "weather":
        return await weather(String(args.place || ""), Number(args.days) || 3);
      case "wikipedia":
        return await wikipedia(String(args.query || ""));
      case "read_page":
        return await readPage(String(args.url || ""));
      case "web_search": {
        const results = await pcSearch(String(args.query || ""));
        return results.length ? results.map((hit, i) => `${i + 1}. ${hit.title}\n   ${hit.url}\n   ${hit.snippet || ""}`).join("\n") : "No results.";
      }
      case "todo":
        return await todo(agent, args);
      case "start_project": {
        const project = await projects.createProject(String(args.name || ""), agent.name);
        ctx.project = project;
        const template = String(args.template || "");
        if (template && TEMPLATES[template]) {
          if (Object.keys(project.files).length) {
            return `${project.name} already has files (${Object.keys(project.files).join(", ")}), so the template wasn't used. Build on them.`;
          }
          for (const [path, body] of Object.entries(templateFiles(template, project.name))) {
            await projects.writeFile(project, path, body, agent.name);
          }
          return `Started ${project.name} from the ${template} template: ${Object.keys(project.files).join(", ")}. Now make it the user's: rewrite index.html with real content for this job (keep the structure and class names), set the colours at the top of styles.css, and replace every placeholder line.`;
        }
        return `Working in the project ${project.name}. Files: ${Object.keys(project.files).join(", ") || "none yet"}.`;
      }
      case "write_file": {
        const project = await needProject(agent, ctx);
        const name = await projects.writeFile(project, args.path, args.content, agent.name);
        return `Wrote ${name} in ${project.name} (${String(args.content || "").length.toLocaleString()} characters).`;
      }
      case "read_file": {
        const project = await needProject(agent, ctx);
        const name = projects.cleanPath(args.path);
        const body = project.files[name];
        return body === undefined ? `There is no ${name} in ${project.name}. Files: ${Object.keys(project.files).join(", ") || "none"}.` : body.slice(0, 24000);
      }
      case "edit_file": {
        const project = await needProject(agent, ctx);
        await projects.editFile(project, args.path, String(args.find || ""), String(args.replace ?? ""), agent.name);
        return `Changed ${args.path} in ${project.name}.`;
      }
      case "list_files": {
        const project = await needProject(agent, ctx);
        const names = Object.keys(project.files);
        return names.length ? names.map((name) => `${name} (${project.files[name].length.toLocaleString()} characters)`).join("\n") : `${project.name} has no files yet.`;
      }
      case "delete_file": {
        const project = await needProject(agent, ctx);
        await projects.deleteFile(project, args.path, agent.name);
        return `Deleted ${args.path}.`;
      }
      case "restore_file": {
        const project = await needProject(agent, ctx);
        const kept = projects.versions(project, args.path);
        const back = Number(args.versions_back);
        if (!back) {
          return kept.length
            ? `${projects.cleanPath(args.path)} has ${kept.length} earlier version(s): ${kept.map((row, i) => `${i + 1} (${Math.max(0, Math.round((Date.now() - row.at) / 60000))} min ago)`).join(", ")}.`
            : `${projects.cleanPath(args.path)} has no earlier versions.`;
        }
        const name = await projects.restoreFile(project, args.path, back, agent.name);
        return `Restored ${name} to the version from ${back} change(s) ago. The version it replaced is kept, so this can be undone too.`;
      }
      case "find_images":
        return await findImagesText(String(args.query || ""), Number(args.count) || 5, String(args.orientation || ""));
      case "polish_check": {
        const project = await needProject(agent, ctx);
        const notes = polishNotes(project.files);
        feed(agent.name, `Polish check on ${project.name}: ${notes.length ? `${notes.length} suggestions` : "looks finished"}.`);
        if (!Object.keys(project.files).some((name) => /\.html?$/i.test(name))) return "There are no web pages to polish in this project.";
        return notes.length ? `${notes.length} polish suggestion(s):\n${notes.map((note) => `- ${note}`).join("\n")}` : "The pages look finished: nothing to polish.";
      }
      case "look_at_site": {
        const project = await needProject(agent, ctx);
        const looks = await lookAtSite(project);
        if (!looks) return `${project.name} has no web page to look at yet. Write index.html first.`;
        const report = describeLook(looks);
        feed(agent.name, report.split("\n")[0]);
        return report;
      }
      case "check_project": {
        const project = await needProject(agent, ctx);
        const problems = projects.checkProject(project);
        feed(agent.name, `Checked ${project.name}: ${problems.length ? `${problems.length} problems` : "all good"}.`);
        return problems.length ? `Problems in ${project.name}:\n${problems.map((p) => `- ${p}`).join("\n")}` : `${project.name} passed every check.`;
      }
      case "ask_agent":
        if (!hooks.delegate) return "Teammates can't be reached right now.";
        return await hooks.delegate(agent, String(args.agent || ""), String(args.task || ""), String(args.project || ""), ctx);
      case "team_status":
        return hooks.teamStatus ? hooks.teamStatus() : "Nobody is working.";
      case "learn":
        if (!hooks.learn) return "Learning isn't available.";
        return await hooks.learn(String(args.topic || ""), String(args.depth || "normal"), agent.name);
      default:
        return `There is no tool called ${call.name}.`;
    }
  } catch (error) {
    return `${call.name} failed: ${error.message}`;
  }
}

async function needProject(agent, ctx) {
  if (ctx.project) return ctx.project;
  const latest = state.projects[0];
  if (latest) {
    ctx.project = latest;
    return latest;
  }
  ctx.project = await projects.createProject(`${agent.name}'s project`, agent.name);
  return ctx.project;
}

// ------------------------------------------------------------------ memory

export async function remember(agent, raw) {
  const clean = raw.trim();
  if (!clean) return "Nothing to remember.";
  const same = state.memories.find((memory) => memory.text.toLowerCase() === clean.toLowerCase());
  if (same) return `Already remembered: ${same.text}`;
  state.memories.unshift({ id: uid(), agent_id: agent.id, text: clean.slice(0, 2000), created_at: Date.now(), synced: false });
  await save.memories();
  changed("memory");
  feed(agent.name, `Remembered: ${clean.slice(0, 90)}`);
  syncSoon();
  return `Saved to memory: ${clean}`;
}

/** Memories from the PC reach only brains that keep them private, unless allowed. */
export function pcMemoryAllowed(agent) {
  if (!state.settings.pc || !state.pcMemories.length) return false;
  return isPrivate(agent) || Boolean(state.settings.cloudSeesPc);
}

export function recall(agent, query, limit) {
  const terms = new Set(words(query));
  const score = (value) => words(value).reduce((sum, word) => sum + (terms.has(word) ? 1 : 0), 0);
  const rows = state.memories.map((memory) => ({ text: memory.text, at: memory.created_at, score: score(memory.text), from: "" }));
  if (pcMemoryAllowed(agent)) {
    for (const memory of state.pcMemories) rows.push({ text: memory.text, at: memory.created_at, score: score(memory.text), from: "from your PC" });
  }
  return rows
    .filter((row) => row.score > 0)
    .sort((a, b) => b.score - a.score || b.at - a.at)
    .slice(0, limit);
}

// -------------------------------------------------------------------- maths

export function formatNumber(value) {
  if (!Number.isFinite(value)) throw new Error("that isn't a number");
  return Number.isInteger(value) ? String(value) : String(Number(value.toPrecision(12)));
}

/** A small, safe maths reader: numbers, + - * / % ^, brackets, and a few functions. */
export function calculate(source) {
  const expression = source
    .toLowerCase()
    .replace(/×/g, "*")
    .replace(/÷/g, "/")
    .replace(/,/g, "")
    .replace(/(\d+(?:\.\d+)?)\s*%\s*of\s*/g, "($1/100)*");
  const tokens = expression.match(/\d+(?:\.\d+)?(?:e[+-]?\d+)?|[a-z]+|\*\*|[-+*/%^(),]|\S/g) || [];
  let index = 0;
  const peek = () => tokens[index];
  const take = (expected) => {
    const token = tokens[index++];
    if (expected && token !== expected) throw new Error(`expected ${expected}`);
    return token;
  };
  const FUNCTIONS = { sqrt: Math.sqrt, abs: Math.abs, round: Math.round, floor: Math.floor, ceil: Math.ceil, log: Math.log10, ln: Math.log, sin: Math.sin, cos: Math.cos, tan: Math.tan, min: Math.min, max: Math.max };
  const CONSTANTS = { pi: Math.PI, e: Math.E };
  const sum = () => {
    let value = product();
    while (peek() === "+" || peek() === "-") value = take() === "+" ? value + product() : value - product();
    return value;
  };
  const product = () => {
    let value = power();
    while (peek() === "*" || peek() === "/" || peek() === "%") {
      const op = take();
      const right = power();
      value = op === "*" ? value * right : op === "/" ? value / right : value % right;
    }
    return value;
  };
  const power = () => {
    const base = unary();
    if (peek() === "^" || peek() === "**") {
      take();
      return base ** power();
    }
    return base;
  };
  const unary = () => {
    if (peek() === "-") {
      take();
      return -unary();
    }
    if (peek() === "+") {
      take();
      return unary();
    }
    return atom();
  };
  const atom = () => {
    const token = take();
    if (token === undefined) throw new Error("the sum ended early");
    if (token === "(") {
      const value = sum();
      take(")");
      return value;
    }
    if (/^\d/.test(token)) return parseFloat(token);
    if (token in CONSTANTS) return CONSTANTS[token];
    if (token in FUNCTIONS) {
      take("(");
      const args = [sum()];
      while (peek() === ",") {
        take();
        args.push(sum());
      }
      take(")");
      return FUNCTIONS[token](...args);
    }
    throw new Error(`can't read "${token}"`);
  };
  const value = sum();
  if (index < tokens.length) throw new Error(`can't read "${tokens[index]}"`);
  return value;
}

// ------------------------------------------------------------------ the web

async function getJson(url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(url, { signal: controller.signal });
    if (!response.ok) throw new Error(`the service answered ${response.status}`);
    return await response.json();
  } catch (error) {
    if (error.name === "AbortError") throw new Error("it took too long");
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

const WEATHER = {
  0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "icy fog",
  51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
  66: "freezing rain", 67: "heavy freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
  80: "light showers", 81: "showers", 82: "violent showers", 85: "snow showers", 86: "heavy snow showers",
  95: "thunderstorms", 96: "thunderstorms with hail", 99: "severe thunderstorms with hail",
};

export async function weather(place, days) {
  if (!place.trim()) throw new Error("say which town or city");
  const found = await getJson(`https://geocoding-api.open-meteo.com/v1/search?count=1&language=en&format=json&name=${encodeURIComponent(place)}`);
  const spot = found.results && found.results[0];
  if (!spot) return `No place called ${place} was found.`;
  const count = Math.max(1, Math.min(7, days));
  const data = await getJson(
    `https://api.open-meteo.com/v1/forecast?latitude=${spot.latitude}&longitude=${spot.longitude}&timezone=auto&forecast_days=${count}` +
      "&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m" +
      "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
  );
  const now = data.current || {};
  const where = [spot.name, spot.admin1, spot.country].filter(Boolean).join(", ");
  const lines = [
    `Weather in ${where}: now ${Math.round(now.temperature_2m)}°C (feels like ${Math.round(now.apparent_temperature)}°C), ${WEATHER[now.weather_code] || "mixed weather"}, wind ${Math.round(now.wind_speed_10m)} km/h, humidity ${Math.round(now.relative_humidity_2m)}%.`,
  ];
  const daily = data.daily || {};
  (daily.time || []).forEach((day, i) => {
    const label = i === 0 ? "Today" : i === 1 ? "Tomorrow" : new Date(`${day}T12:00`).toLocaleDateString("en", { weekday: "long" });
    const rain = (daily.precipitation_probability_max || [])[i];
    lines.push(
      `${label}: ${WEATHER[(daily.weather_code || [])[i]] || "mixed weather"}, ${Math.round(daily.temperature_2m_max[i])}°C high, ${Math.round(daily.temperature_2m_min[i])}°C low${rain === null || rain === undefined ? "" : `, ${rain}% chance of rain`}.`
    );
  });
  return lines.join("\n");
}

export async function wikipedia(query) {
  if (!query.trim()) throw new Error("say what to look up");
  const found = await getJson(`https://en.wikipedia.org/w/api.php?action=query&list=search&format=json&origin=*&srlimit=3&srsearch=${encodeURIComponent(query)}`);
  const hits = (found.query && found.query.search) || [];
  if (!hits.length) return `Wikipedia has nothing on ${query}.`;
  const title = hits[0].title;
  const page = await getJson(`https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(title.replace(/ /g, "_"))}`);
  const link = (page.content_urls && page.content_urls.mobile && page.content_urls.mobile.page) || "";
  const others = hits.slice(1).map((hit) => hit.title);
  return `${page.title}: ${page.extract || "(no summary)"}${link ? `\nSource: ${link}` : ""}${others.length ? `\nAlso: ${others.join(", ")}` : ""}`;
}

export async function readPage(url) {
  if (!/^https?:\/\//i.test(url)) throw new Error("give a full https:// address");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30000);
  try {
    // A free reader service turns any page into plain text a phone can fetch.
    const response = await fetch(`https://r.jina.ai/${url}`, { signal: controller.signal, headers: { Accept: "text/plain" } });
    if (!response.ok) throw new Error(`the page couldn't be read (${response.status})`);
    const body = await response.text();
    return body.slice(0, 12000);
  } catch (error) {
    if (error.name === "AbortError") throw new Error("the page took too long");
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

// ------------------------------------------------------------------- photos

const OPENVERSE = "https://api.openverse.org/v1/images/";

/** Free photos from Openverse that a website may use, with credit lines. */
export async function findImages(query, count = 5, orientation = "") {
  const clean = query.trim().replace(/\s+/g, " ").slice(0, 120);
  if (!clean) throw new Error("say what the pictures should show");
  const params = new URLSearchParams({ q: clean, page_size: String(Math.max(1, Math.min(10, count))), license_type: "commercial", mature: "false" });
  if (["wide", "tall", "square"].includes(orientation)) params.set("aspect_ratio", orientation);
  let data;
  try {
    data = await getJson(`${OPENVERSE}?${params}`);
  } catch (error) {
    if (/429/.test(error.message)) throw new Error("the free photo search is busy; try again in a minute");
    throw error;
  }
  return (data.results || [])
    .filter((item) => item && /^https:\/\//.test(String(item.url || "")))
    .map((item) => {
      const licence = String(item.license || "").toUpperCase();
      const creator = item.creator || "unknown";
      return {
        url: item.url,
        width: Number(item.width) || 0,
        height: Number(item.height) || 0,
        title: String(item.title || "Photo").slice(0, 80),
        credit: ["CC0", "PDM"].includes(licence) ? `Photo by ${creator} (public domain)` : `Photo by ${creator}, CC ${licence} ${item.license_version || ""}`.trim(),
      };
    });
}

async function findImagesText(query, count, orientation) {
  const found = await findImages(query, count, orientation);
  if (!found.length) return `No free photos for "${query}". Try fewer or plainer words.`;
  return [
    ...found.map((image, i) => `${i + 1}. ${image.title} (${image.width}x${image.height}) ${image.url}\n   Credit: ${image.credit}`),
    'Use one with <img src="its address" alt="what it shows" width="…" height="…">, and put its credit in the footer.',
  ].join("\n");
}

// -------------------------------------------------------------------- to-dos

export function parseDue(raw, now = new Date()) {
  const text = String(raw || "").trim().toLowerCase();
  if (!text) return 0;
  let match = text.match(/^in\s+(\d+)\s*(minute|min|hour|hr|day)s?$/);
  if (match) {
    const unit = match[2].startsWith("h") ? 3600000 : match[2].startsWith("d") ? 86400000 : 60000;
    return now.getTime() + Number(match[1]) * unit;
  }
  const day = new Date(now);
  if (/tomorrow/.test(text)) day.setDate(day.getDate() + 1);
  if (/tonight/.test(text) && !/\d/.test(text)) {
    day.setHours(20, 0, 0, 0);
    return day.getTime();
  }
  match = text.match(/(\d{1,2})(?::(\d{2}))?\s*(am|pm)?/);
  if (match) {
    let hour = Number(match[1]);
    if (match[3] === "pm" && hour < 12) hour += 12;
    if (match[3] === "am" && hour === 12) hour = 0;
    day.setHours(hour, Number(match[2] || 0), 0, 0);
    if (!/tomorrow/.test(text) && day.getTime() < now.getTime()) day.setDate(day.getDate() + 1);
    return day.getTime();
  }
  if (/tomorrow/.test(text)) {
    day.setHours(9, 0, 0, 0);
    return day.getTime();
  }
  const parsed = Date.parse(raw);
  return Number.isNaN(parsed) ? 0 : parsed;
}

export async function addTodo(textValue, due, by) {
  const item = { id: uid().slice(0, 6), text: textValue.trim().slice(0, 300), due_at: parseDue(due), done: false, notified: false, by, created_at: Date.now() };
  if (!item.text) throw new Error("say what to add");
  state.todos.unshift(item);
  await save.todos();
  changed("todos");
  return item;
}

async function todo(agent, args) {
  const action = String(args.action || "list").toLowerCase();
  if (action === "add") {
    const item = await addTodo(String(args.text || ""), String(args.due || ""), agent.name);
    feed(agent.name, `Added to your list: ${item.text}`);
    return `Added: ${item.text}${item.due_at ? ` (reminder ${new Date(item.due_at).toLocaleString()})` : ""} [id ${item.id}]`;
  }
  if (action === "done") {
    const wanted = String(args.text || "").toLowerCase();
    const item = state.todos.find((row) => !row.done && (row.id === wanted || row.text.toLowerCase().includes(wanted)));
    if (!item) return `Nothing open matches "${args.text}".`;
    item.done = true;
    await save.todos();
    changed("todos");
    return `Ticked off: ${item.text}`;
  }
  const open = state.todos.filter((row) => !row.done);
  return open.length ? open.map((row) => `- ${row.text}${row.due_at ? ` (due ${new Date(row.due_at).toLocaleString()})` : ""} [id ${row.id}]`).join("\n") : "The to-do list is empty.";
}

export { agentByName };
