// Fixed tables: names, traits, jobs and buildings.

export const FIRST_NAMES = [
  "Ava", "Ben", "Cleo", "Dev", "Esme", "Finn", "Gus", "Hana", "Ivo", "Juno",
  "Kai", "Lena", "Milo", "Nia", "Otto", "Pia", "Quin", "Rosa", "Sami", "Tess",
  "Umar", "Vera", "Wren", "Xavi", "Yara", "Zeke", "Arlo", "Bea", "Cass", "Dora",
  "Eli", "Faye", "Gil", "Hugo", "Iris", "Jude", "Kira", "Leo", "Mara", "Ned",
  "Opal", "Pip", "Remy", "Sol", "Theo", "Uma", "Vic", "Willa", "Yusuf", "Zara",
  "Abel", "Bree", "Cyrus", "Daisy", "Emil", "Flora", "Grey", "Hazel", "Ines", "Jory",
  "Kofi", "Luz", "Moss", "Noor", "Orla", "Percy", "Ruby", "Silas", "Tomas", "Ula",
  "Vik", "Wade", "Yoko", "Zion", "Anya", "Bram", "Coral", "Dex", "Edie", "Fox",
  "Greta", "Hal", "Ilse", "Jett", "Kit", "Lark", "Mei", "Nils", "Oona", "Priya",
  "Rafe", "Suki", "Tobin", "Una", "Vale", "Wynn", "Ari", "Bo", "Cato", "Dua",
];

export const LAST_NAMES = [
  "Ashby", "Brook", "Carver", "Dale", "Ember", "Fairweather", "Glen", "Holt",
  "Ivy", "Juniper", "Kettle", "Lark", "Miller", "North", "Oakes", "Penn",
  "Quill", "Reed", "Stone", "Thatcher", "Underhill", "Vance", "Wells", "Yew",
  "Barley", "Copper", "Dunmore", "Finch", "Gale", "Hearth", "Marsh", "Rowan",
];

const VILLAGE_A = ["Oak", "Mill", "Stone", "Brook", "Elm", "Fox", "Ash", "Thorn", "Bram", "Hazel", "Clover", "Briar", "Fern", "Marsh", "Pine", "Wren"];
const VILLAGE_B = ["wick", "ford", "by", "dale", "field", "stead", "haven", "ton", "holm", "mere", "bury", "well"];
export const VILLAGE_COLORS = ["#e8b04a", "#5fb0e8", "#e86a5f", "#9b7be8", "#5fe8a2", "#e85fc0"];
export const villageName = (r) => VILLAGE_A[Math.floor(r() * VILLAGE_A.length)] + VILLAGE_B[Math.floor(r() * VILLAGE_B.length)];

// Personality traits. Each villager gets two that don't clash.
export const TRAITS = {
  friendly: { label: "Friendly", icon: "😊", social: 1.5, warmth: 2 },
  shy: { label: "Shy", icon: "🙈", social: 0.55, warmth: 0 },
  grumpy: { label: "Grumpy", icon: "😠", social: 0.8, warmth: -2 },
  cheerful: { label: "Cheerful", icon: "🌞", social: 1.2, warmth: 1, mood: 10 },
  lazy: { label: "Lazy", icon: "🛌", work: 0.6 },
  hardworking: { label: "Hard-working", icon: "💪", work: 1.4 },
  curious: { label: "Curious", icon: "🔍", social: 1.1 },
  gossip: { label: "Gossip", icon: "🗣️", social: 1.6, spread: 1 },
  romantic: { label: "Romantic", icon: "💘", social: 1.1, romance: 1 },
  brave: { label: "Brave", icon: "🛡️" },
  kind: { label: "Kind", icon: "💛", warmth: 2 },
  ambitious: { label: "Ambitious", icon: "⭐", work: 1.2 },
};
export const CLASHES = [
  ["friendly", "grumpy"], ["shy", "gossip"], ["lazy", "hardworking"],
  ["cheerful", "grumpy"], ["shy", "brave"], ["lazy", "ambitious"], ["kind", "grumpy"],
];

export const JOBS = {
  farmer: { label: "Farmer", icon: "🌾", color: "#7cb342", skill: "farming" },
  woodcutter: { label: "Woodcutter", icon: "🪓", color: "#8d6e63", skill: "woodcut" },
  miner: { label: "Miner", icon: "⛏️", color: "#78909c", skill: "mining" },
  builder: { label: "Builder", icon: "🔨", color: "#ffb300", skill: "building" },
  keeper: { label: "Tavern keeper", icon: "🍺", color: "#d81b60", skill: "social", place: "tavern" },
  merchant: { label: "Merchant", icon: "💰", color: "#8e24aa", skill: "social", place: "market" },
  teacher: { label: "Teacher", icon: "📚", color: "#1e88e5", skill: "learning", place: "school" },
  healer: { label: "Healer", icon: "🌿", color: "#f5f5f5", skill: "learning", place: "clinic" },
  priest: { label: "Priest", icon: "🕯️", color: "#fdd835", skill: "social", place: "temple" },
  guard: { label: "Guard", icon: "🗡️", color: "#c62828", skill: "fighting", place: "tower" },
  idle: { label: "Unemployed", icon: "🎈", color: "#bdbdbd", skill: "social" },
  child: { label: "Child", icon: "🧸", color: "#4fc3f7", skill: "learning" },
  elder: { label: "Elder", icon: "🦯", color: "#9e9e9e", skill: "social" },
};
export const WORK_JOBS = ["farmer", "woodcutter", "miner", "builder", "keeper", "merchant", "teacher", "healer", "priest", "guard", "idle"];

export const SKILLS = ["farming", "woodcut", "mining", "building", "social", "learning", "fighting"];

// Buildings. work = builder-minutes; jobs = workers it employs.
export const BUILDINGS = {
  townhall: { name: "Town Hall", icon: "🏛️", w: 3, h: 3, cost: {}, work: 0, wall: "#c9a27a", roof: "#8c3b2e", desc: "The village store and heart. Drop a villager far away to found another.", build: false },
  house: { name: "House", icon: "🏠", w: 2, h: 2, cost: { wood: 12, stone: 2 }, work: 180, cap: 4, wall: "#d7b98e", roof: "#b5523b", desc: "Home for up to four. Couples with a home can have children." },
  farm: { name: "Farm", icon: "🌾", w: 3, h: 3, cost: { wood: 5 }, work: 90, jobs: 3, job: "farmer", desc: "Farmers grow food here. Rain helps." },
  tavern: { name: "Tavern", icon: "🍺", w: 3, h: 2, cost: { wood: 20, stone: 6 }, work: 360, jobs: 1, job: "keeper", wall: "#a1754f", roof: "#6d3b26", desc: "Evenings, gossip and parties." },
  market: { name: "Market", icon: "🛒", w: 3, h: 2, cost: { wood: 16, stone: 8 }, work: 300, jobs: 1, job: "merchant", wall: "#e0c9a6", roof: "#7b4fa0", desc: "A merchant trades for gold." },
  school: { name: "School", icon: "📚", w: 3, h: 2, cost: { wood: 18, stone: 10 }, work: 320, jobs: 1, job: "teacher", wall: "#e8dcc4", roof: "#3a6fb0", desc: "Children learn and grow skills." },
  clinic: { name: "Clinic", icon: "🌿", w: 2, h: 2, cost: { wood: 12, stone: 10 }, work: 260, jobs: 1, job: "healer", wall: "#f2efe6", roof: "#3f9a6b", desc: "A healer cures the sick." },
  temple: { name: "Temple", icon: "🕯️", w: 3, h: 3, cost: { wood: 15, stone: 25, gold: 10 }, work: 480, jobs: 1, job: "priest", wall: "#d9d4c7", roof: "#c9a227", desc: "Lifts everyone's spirits." },
  well: { name: "Well", icon: "🪣", w: 1, h: 1, cost: { stone: 6 }, work: 60, desc: "A meeting spot. Puts out fires faster nearby." },
  park: { name: "Park", icon: "🌳", w: 2, h: 2, cost: { wood: 4 }, work: 60, desc: "Fun and fresh air." },
  tower: { name: "Watchtower", icon: "🗼", w: 2, h: 2, cost: { wood: 12, stone: 15 }, work: 300, jobs: 2, job: "guard", wall: "#9e9e9e", roof: "#5d4037", desc: "Guards fight wolves." },
  statue: { name: "Statue", icon: "🗿", w: 1, h: 1, cost: { stone: 10, gold: 5 }, work: 120, desc: "Honours a villager. Pride and joy." },
};
export const BUILD_MENU = ["house", "farm", "tavern", "market", "school", "clinic", "temple", "well", "park", "tower", "statue"];

export const FARM_NAMES = ["Sunny", "Golden", "Clover", "Windy", "Green", "Honey", "Barley", "Meadow", "Rye", "Turnip"];
export const TAVERN_NAMES = ["The Rusty Mug", "The Sleepy Fox", "The Golden Goose", "The Merry Kettle", "The Crooked Lantern", "The Tipsy Badger"];
export const PARK_NAMES = ["Willow Park", "Rose Garden", "Daisy Green", "Fern Glade", "Lantern Park"];

export const SKIN = ["#f1c9a5", "#e0ac7e", "#c68a5c", "#a0683f", "#7a4a2b", "#5a3520"];
export const HAIR = ["#2b1d14", "#5a3a22", "#8b5a2b", "#c48a3a", "#e6c36a", "#a33a1f", "#1a1a1a", "#6b6b6b"];

export const IDEAS = [
  "the village needs a bigger farm",
  "there's treasure buried in the hills",
  "the old well is haunted",
  "we should hold a harvest festival",
  "the wolves are getting bolder",
  "someone should write down our history",
];
