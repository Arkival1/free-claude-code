"""The Lab: real chemistry results, products, materials, gadgets, and Jarvis."""

import httpx
import pytest

from free_claude_code.studio.lab import recipes
from free_claude_code.studio.lab.bench import LAB_PROMPT, LabBench
from free_claude_code.studio.lab.chemicals import CHEMICALS, resolve
from free_claude_code.studio.lab.elements import BY_SYMBOL, ELEMENTS
from free_claude_code.studio.lab.formula import composition, molar_mass, parse, pretty
from free_claude_code.studio.lab.materials import blend
from free_claude_code.studio.lab.safety import refusal
from free_claude_code.studio.lab.sim import LabError, simulate
from free_claude_code.studio.lab.tech import simulate_build, standard_resistor
from free_claude_code.studio.llm import LLMReply
from free_claude_code.studio.tools import (
    DEFAULT_TOOL_NAMES,
    MAIN_TOOL_NAMES,
    TOOL_SPEC_BY_NAME,
)
from tests.api.support import create_test_app

from .conftest import tool_reply


def gases(result):
    return {gas["formula"]: gas for gas in result["vessel"]["gases"]}


def solids(result):
    return {solid["formula"]: solid for solid in result["vessel"]["precipitates"]}


def warnings(result):
    return " ".join(h["text"] for h in result["hazards"] if h["level"] == "danger")


# ------------------------------------------------------------ the shelves


def test_every_element_is_on_the_periodic_table():
    assert len(ELEMENTS) == 118
    assert len(BY_SYMBOL) == 118
    assert [e.number for e in ELEMENTS] == list(range(1, 119))
    assert BY_SYMBOL["Og"].name == "Oganesson"
    assert BY_SYMBOL["U"].view()["radioactive"]
    assert BY_SYMBOL["Cu"].view()["flame"]["name"] == "blue-green"
    # Any element can go in the beaker, not only the shelf chemicals.
    chlorine, sodium, uranium = (resolve(n) for n in ("Cl", "sodium", "Uranium"))
    assert chlorine is not None and chlorine.formula == "Cl2"
    assert sodium is not None and sodium.id == "sodium-metal"
    assert uranium is not None and uranium.hazards == ("radioactive",)
    assert len({c.id for c in CHEMICALS}) == len(CHEMICALS)


def test_formulas_are_read_and_weighed():
    assert parse("CuSO4·5H2O") == {"Cu": 1, "S": 1, "O": 9, "H": 10}
    assert parse("Ca(OH)2") == {"Ca": 1, "O": 2, "H": 2}
    assert parse("Al2(SO4)3") == {"Al": 2, "S": 3, "O": 12}
    assert molar_mass("H2O") == pytest.approx(18.015, abs=0.01)
    assert molar_mass("NaCl") == pytest.approx(58.44, abs=0.01)
    water = {row["symbol"]: row["mass_percent"] for row in composition("H2O")}
    assert water["O"] == pytest.approx(88.81, abs=0.05)
    assert pretty("H2SO4") == "H₂SO₄"


# ------------------------------------------------------------ mixing


def test_lead_nitrate_and_potassium_iodide_rain_yellow():
    result = simulate(
        [{"id": "lead-nitrate", "amount": 10}, {"id": "potassium-iodide", "amount": 10}]
    )
    lead_iodide = solids(result)["PbI2"]
    assert lead_iodide["colour"] == "#ffd400"
    # 10 mL of 0.1 M KI makes 0.0005 mol PbI2 (461 g/mol).
    assert lead_iodide["grams"] == pytest.approx(0.2305, abs=0.002)
    assert "Pb²⁺(aq) + 2I⁻(aq) → PbI₂(s)" in [
        r["equation"] for r in result["reactions"]
    ]
    assert "Toxic" in " ".join(h["text"] for h in result["hazards"])


def test_vinegar_and_baking_soda_fizz_and_feel_cold():
    result = simulate(
        [{"id": "vinegar", "amount": 50}, {"id": "baking soda", "amount": 5}]
    )
    assert gases(result)["CO2"]["ml"] > 500
    assert result["vessel"]["temperature_c"] < 20
    assert 7 < result["vessel"]["ph"] < 9  # leftover baking soda


def test_neutralising_acid_warms_and_the_indicator_turns_pink():
    exact = simulate(
        [
            {"id": "hydrochloric-acid", "amount": 20},
            {"id": "sodium-hydroxide", "amount": 20},
            {"id": "phenolphthalein", "amount": 1},
        ]
    )
    assert exact["vessel"]["ph"] == pytest.approx(7.0, abs=0.01)
    assert exact["vessel"]["temperature_c"] > 25
    alkaline = simulate(
        [
            {"id": "hydrochloric-acid", "amount": 10},
            {"id": "sodium-hydroxide", "amount": 20},
            {"id": "phenolphthalein", "amount": 1},
        ]
    )
    assert alkaline["vessel"]["ph"] > 12
    assert alkaline["vessel"]["colour"] == "#d4007a"
    cabbage = simulate(
        [{"id": "red-cabbage", "amount": 20}, {"id": "vinegar", "amount": 10}]
    )
    assert "Red cabbage juice turns pink." in cabbage["observations"]


def test_metals_fizz_in_acid_and_sodium_skates_on_water():
    zinc = simulate([{"id": "zinc", "amount": 1}, {"id": "hcl", "amount": 20}])
    assert "H2" in gases(zinc)
    assert "Zn(s) + 2H⁺ → Zn²⁺ + H₂↑" in [r["equation"] for r in zinc["reactions"]]
    copper = simulate([{"id": "copper", "amount": 1}, {"id": "hcl", "amount": 20}])
    assert not copper["reactions"]
    assert any("below hydrogen" in seen for seen in copper["observations"])
    sodium = simulate([{"id": "Na", "amount": 0.2}, {"id": "water", "amount": 50}])
    assert gases(sodium)["H2"]["level"] == "violent"
    assert sodium["vessel"]["ph"] > 12
    assert "reacts violently with water" in warnings(sodium)


def test_displacement_grows_silver_and_ammonia_turns_copper_royal_blue():
    silver = simulate(
        [{"id": "silver-nitrate", "amount": 20}, {"id": "copper", "amount": 2}]
    )
    assert "Cu(s) + 2Ag⁺(aq) → Cu²⁺(aq) + 2Ag(s)" in [
        r["equation"] for r in silver["reactions"]
    ]
    assert "silver metal" in [s["name"] for s in silver["vessel"]["solids"]]
    blue = simulate(
        [{"id": "copper-sulfate", "amount": 5}, {"id": "ammonia", "amount": 20}]
    )
    assert blue["vessel"]["colour"] == "#1036d6"
    assert blue["vessel"]["colour_steps"] == ["#6fb7ff", "#1036d6"]
    hydroxide = simulate(
        [
            {"id": "copper-sulfate", "amount": 10},
            {"id": "sodium-hydroxide", "amount": 5},
        ]
    )
    assert "Cu(OH)2" in solids(hydroxide)


def test_elephant_toothpaste_and_dangerous_household_mixes():
    foam = simulate(
        [
            {"id": "hydrogen-peroxide-strong", "amount": 30},
            {"id": "dish-soap", "amount": 5},
            {"id": "potassium-iodide", "amount": 10},
        ]
    )
    assert foam["vessel"]["foam"] == 1.0
    assert "elephant-toothpaste" in foam["vessel"]["effects"]
    assert "O2" in gases(foam)
    chlorine = simulate(
        [{"id": "bleach", "amount": 10}, {"id": "vinegar", "amount": 10}]
    )
    assert "Cl2" in gases(chlorine)
    assert "toxic chlorine" in warnings(chlorine)
    chloramine = simulate(
        [{"id": "bleach", "amount": 10}, {"id": "ammonia", "amount": 10}]
    )
    assert "chloramine" in warnings(chloramine)


def test_tests_colours_and_heat():
    starch = simulate(
        [
            {"id": "starch", "amount": 1},
            {"id": "water", "amount": 20},
            {"id": "iodine", "amount": 1},
        ]
    )
    assert starch["vessel"]["colour"] == "#141a4d"
    crystals = simulate([{"id": "copper-sulfate-crystals", "amount": 5}], heat=True)
    assert crystals["vessel"]["solids"][0]["colour"] == "#f2f2ee"
    flame = simulate([{"id": "copper-sulfate", "amount": 5}], flame=True)
    assert flame["vessel"]["flame"]["name"] == "blue-green"
    oil = simulate([{"id": "olive oil", "amount": 10}, {"id": "water", "amount": 20}])
    assert [layer["name"] for layer in oil["vessel"]["layers"]] == [
        "watery layer",
        "oil layer",
    ]
    cold = simulate(
        [{"id": "ammonium-nitrate", "amount": 20}, {"id": "water", "amount": 50}]
    )
    assert cold["vessel"]["temperature_c"] < 5
    salt = simulate([{"id": "salt", "amount": 50}, {"id": "water", "amount": 50}])
    assert salt["vessel"]["solids"][0]["grams"] == pytest.approx(32, abs=0.1)
    fire = simulate(
        [{"id": "sugar", "amount": 5}, {"id": "potassium-nitrate", "amount": 5}],
        heat=True,
    )
    assert "fire-risk" in fire["vessel"]["effects"]
    assert not fire["reactions"]
    assert simulate([{"id": "unobtainium"}])["unknown"] == ["unobtainium"]
    with pytest.raises(LabError):
        simulate([])


# ------------------------------------------------------------ making things


def test_shampoo_lists_every_ingredient_and_element():
    assert recipes.product_key("hey jarvis make a shampoo") == "shampoo"
    assert recipes.product_key("sun cream") == "sunscreen"
    assert recipes.product_key("Elephant toothpaste (demo)") == "elephant-toothpaste"
    assert recipes.build_key("a torch") == "flashlight"
    shampoo = recipes.template_product("shampoo")
    percents = [row["percent"] for row in shampoo["ingredients"]]
    assert sum(percents) == pytest.approx(100, abs=0.01)
    names = [row["id"] for row in shampoo["ingredients"]]
    assert names[:3] == ["water", "sles", "capb"]
    assert sum(row["grams"] for row in shampoo["ingredients"]) == pytest.approx(250)
    elements = {row["symbol"] for row in shampoo["elements"]}
    assert {"O", "H", "C", "Na", "Cl", "S", "N"} <= elements
    sles = next(row for row in shampoo["ingredients"] if row["id"] == "sles")
    assert sles["formula"] == "C16H33NaO6S"
    assert {row["symbol"] for row in sles["elements"]} == {"C", "H", "Na", "O", "S"}
    for key in recipes.PRODUCTS:
        product = recipes.template_product(key)
        assert not product["unknown"], key
        total = sum(row["percent"] for row in product["ingredients"])
        assert total == pytest.approx(100, abs=0.01), key


def test_materials_and_alloys():
    bronze = blend([{"id": "copper", "percent": 88}, {"id": "tin", "percent": 12}])
    assert bronze["known"] and bronze["material"]["name"] == "Bronze"
    steel = blend([{"id": "Fe", "percent": 99.7}, {"id": "C", "percent": 0.3}])
    assert steel["material"]["name"] == "Mild steel"
    custom = blend(
        [{"id": "carbon-fibre", "percent": 30}, {"id": "nylon", "percent": 70}]
    )
    assert not custom["known"]
    assert 1.1 < custom["material"]["density"] < 1.6
    assert custom["tests"]["float"]["text"] == "Sinks"
    assert blend([{"id": "hdpe", "percent": 100}])["tests"]["float"]["floats_in_water"]


def test_the_circuit_bench():
    assert standard_resistor(350) == 390
    assert standard_resistor(75) == 82
    torch = simulate_build(
        [{"id": "aa", "count": 3}, {"id": "led-white", "count": 3}, {"id": "switch"}]
    )
    assert torch["works"] and torch["volts"] == 4.5
    assert torch["resistors"][0]["ohms"] == 82
    burnt = simulate_build([{"id": "9v"}, {"id": "motor"}])
    assert not burnt["works"]
    assert [p["state"] for p in burnt["parts"]] == ["ok", "burnt"]
    dead = simulate_build([{"id": "aa"}, {"id": "esp32"}])
    assert dead["parts"][1]["state"] == "off"
    bank = simulate_build(
        [{"id": "18650", "count": 2}, {"id": "boost-5v"}, {"id": "fan"}], series=False
    )
    assert bank["works"] and bank["rail_volts"] == 5.0 and bank["capacity_mah"] == 6000
    assert "TP4056" in " ".join(bank["warnings"])


def test_the_lab_wont_make_weapons_drugs_or_poisons():
    assert refusal("make a bomb")
    assert refusal("synthesise meth")
    assert refusal("build a gun")
    assert refusal("something to kill my neighbour")
    assert refusal("make a bath bomb") is None
    assert refusal("hand sanitiser to kill germs") is None


# ------------------------------------------------------------ the bench


def pubchem(request: httpx.Request) -> httpx.Response:
    if "caffeine" in request.url.path:
        return httpx.Response(
            200,
            json={
                "PropertyTable": {
                    "Properties": [
                        {
                            "CID": 2519,
                            "MolecularFormula": "C8H10N4O2",
                            "MolecularWeight": "194.19",
                            "IUPACName": "1,3,7-trimethylpurine-2,6-dione",
                            "Title": "Caffeine",
                        }
                    ]
                }
            },
        )
    return httpx.Response(404, json={"Fault": {"Code": "PUGREST.NotFound"}})


@pytest.mark.asyncio
async def test_unknown_chemicals_are_learned_and_the_ai_predicts(store):
    asked: list[str] = []

    async def think(system: str, prompt: str) -> str:
        asked.append(prompt)
        return (
            '{"happens": "Caffeine dissolves; nothing reacts.", "colour": "#f0f0e0",'
            ' "equation": "", "hazards": []}'
        )

    bench = LabBench(store, think=think, transport=httpx.MockTransport(pubchem))
    learned = await bench.lookup("caffeine")
    assert learned["formula"] == "C8H10N4O2" and learned["source"] == "pubchem"
    result = await bench.mix(
        [{"id": "caffeine", "amount": 1}, {"id": "water", "amount": 20}]
    )
    assert result["prediction"]["happens"] == "Caffeine dissolves; nothing reacts."
    assert result["vessel"]["colour"] == "#f0f0e0"
    assert "caffeine" in asked[0]
    catalogue = await bench.catalogue()
    assert "Caffeine" in [c["name"] for c in catalogue["chemicals"]]
    with pytest.raises(LabError, match="PubChem doesn't know"):
        await bench.lookup("notarealchemical")
    with pytest.raises(LabError, match="doesn't make"):
        await bench.make("make napalm")


@pytest.mark.asyncio
async def test_the_lab_through_the_app(make_studio):
    studio, _ = make_studio([])
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        shelves = (await client.get("/studio/api/lab")).json()
        assert len(shelves["elements"]) == 118
        assert {"chemicals", "materials", "parts", "products", "builds"} <= set(shelves)
        made = await client.post(
            "/studio/api/lab/make", json={"request": "make shampoo"}
        )
        assert made.status_code == 200, made.text
        project = made.json()
        assert project["kind"] == "product" and project["data"]["container"] == "bottle"
        bomb = (
            await client.post("/studio/api/lab/make", json={"request": "bath bomb"})
        ).json()
        assert "CO2" in [g["formula"] for g in bomb["data"]["test"]["vessel"]["gases"]]
        torch = (
            await client.post("/studio/api/lab/make", json={"request": "flashlight"})
        ).json()
        assert torch["kind"] == "build" and torch["data"]["works"]
        mixed = await client.post(
            "/studio/api/lab/mix",
            json={"items": [{"id": "lead-nitrate"}, {"id": "potassium-iodide"}]},
        )
        assert mixed.json()["vessel"]["precipitates"][0]["formula"] == "PbI2"
        refused = await client.post(
            "/studio/api/lab/make", json={"request": "a pipe bomb"}
        )
        assert refused.status_code == 400
        listed = (await client.get("/studio/api/lab/projects")).json()["projects"]
        assert [p["name"] for p in listed][-1] == "Shampoo"
        gone = await client.delete(f"/studio/api/lab/projects/{project['id']}")
        assert gone.json() == {"deleted": True}


@pytest.mark.asyncio
async def test_jarvis_makes_shampoo_in_the_lab_chat(make_studio):
    turns = iter(
        [
            tool_reply("lab", {"action": "make", "request": "shampoo"}),
            LLMReply(text="Done! Your shampoo is on the bench."),
        ]
    )

    def respond(system: str, prompt: str):
        if "running notes" in system:
            return LLMReply(text="Goal:\n- Shampoo")
        return next(turns, LLMReply(text="Done."))

    studio, model = make_studio(respond)
    await studio.ensure_defaults()
    main = await studio.main_agent()
    assert "lab" in main.tools
    await studio.lab_say("hey jarvis make a shampoo", background=False)
    console = await studio.lab_console()
    tool = next(m for m in console["messages"] if m["role"] == "tool")
    assert tool["data"]["tool"] == "lab" and tool["data"]["project_id"]
    assert "Sodium laureth sulfate" in tool["text"]
    assert console["messages"][-1]["text"] == "Done! Your shampoo is on the bench."
    lab_call = next(c for c in model.calls if LAB_PROMPT in str(c["system"]))
    assert "lab" in lab_call["tools"]
    project = await studio.lab.project(tool["data"]["project_id"])
    assert project["made_by"] == main.name
    # The main console chat is a different conversation.
    assert (await studio.main_chat()).id != console["chat_id"]


def test_only_jarvis_gets_the_lab_by_default():
    assert "lab" in MAIN_TOOL_NAMES
    assert "lab" not in DEFAULT_TOOL_NAMES
    properties = TOOL_SPEC_BY_NAME["lab"].parameters["properties"]
    assert isinstance(properties, dict)
    action = properties["action"]
    assert isinstance(action, dict)
    assert action["enum"] == [
        "make",
        "mix",
        "build",
        "material",
        "find",
        "list",
    ]


@pytest.mark.parametrize(
    ("text", "in_lab", "action", "wanted"),
    [
        ("make shampoo", True, "make", "shampoo"),
        ("Jarvis, make shampoo in the lab", False, "make", "shampoo"),
        ("hey jarvis go to the lab and make toothpaste", False, "make", "toothpaste"),
        ("lab: build a flashlight", False, "make", "flashlight"),
        ("mix vinegar and baking soda", True, "mix", "mix vinegar and baking soda"),
        ("heat copper with sulfur in the lab", False, "mix", "heat copper with sulfur"),
    ],
)
def test_lab_jobs_are_read_from_what_the_user_says(text, in_lab, action, wanted):
    from free_claude_code.studio.lab.requests import lab_job

    job = lab_job(text, in_lab=in_lab)
    assert job is not None and (job.action, job.request) == (action, wanted)


@pytest.mark.parametrize(
    ("text", "in_lab"),
    [
        ("make me a website", False),
        ("what is in the lab", False),
        ("whats the best thing to make in the lab", False),
        ("mix it up", True),
    ],
)
def test_other_messages_are_not_lab_jobs(text, in_lab):
    from free_claude_code.studio.lab.requests import lab_job

    assert lab_job(text, in_lab=in_lab) is None


def test_a_mix_names_its_chemicals_and_heat():
    from free_claude_code.studio.lab.requests import lab_job

    job = lab_job("mix copper and sulfur and heat it", in_lab=True)
    assert job is not None and job.heat is True
    assert [item["id"] for item in job.items] == ["copper", "sulfur"]


def _lab_jarvis():
    from free_claude_code.studio.llm import LLMReply

    def respond(system: str, prompt: str):
        return LLMReply(text="Here's your shampoo.")

    return respond


@pytest.mark.asyncio
async def test_saying_make_in_the_lab_chat_makes_it(make_studio):
    studio, model = make_studio(_lab_jarvis())
    await studio.ensure_defaults()

    chat = await studio.lab_say("make shampoo", background=False)

    projects = await studio._lab.projects()
    assert [p["kind"] for p in projects] == ["product"]
    made = [m for m in await studio.transcript(chat.id) if m.author == "lab"]
    assert len(made) == 1 and not made[0].data["failed"]
    note = str(model.calls[-1]["studio_note"])
    assert "Studio already did this in the Lab (make 'shampoo')" in note


@pytest.mark.asyncio
async def test_make_in_the_lab_from_the_main_chat_goes_to_the_lab_agent(
    make_studio,
):
    studio, model = make_studio(_lab_jarvis())
    await studio.ensure_defaults()
    scientist = await studio.agent_by_name("Lab")
    assert scientist is not None

    await studio.main_say("make soap in the lab", background=False)
    await studio.wait_for_background()

    [run] = await studio.runs()
    assert run.agent_id == scientist.id and "make soap" in run.goal.lower()
    # Its model only talked, so Studio ran the make for it.
    assert len(await studio._lab.projects()) == 1
    note = next(
        str(c["studio_note"])
        for c in model.calls
        if "the user's main AI" in str(c["system"])
    )
    assert "went to the Lab agent" in note


@pytest.mark.asyncio
async def test_with_no_lab_agent_studio_makes_it_itself(make_studio):
    studio, _ = make_studio(_lab_jarvis())
    await studio.ensure_defaults()
    scientist = await studio.agent_by_name("Lab")
    assert scientist is not None
    await studio.delete_agent(scientist.id)

    await studio.main_say("make soap in the lab", background=False)

    assert await studio.runs() == ()
    assert len(await studio._lab.projects()) == 1


@pytest.mark.asyncio
async def test_the_lab_still_refuses_what_it_refuses(make_studio):
    studio, model = make_studio(_lab_jarvis())
    await studio.ensure_defaults()

    await studio.lab_say("make a bomb", background=False)

    assert await studio._lab.projects() == []
    assert "and the Lab said:" in str(model.calls[-1]["studio_note"])


def test_baking_soda_in_vinegar_stays_realistic():
    from free_claude_code.studio.lab.sim import simulate

    result = simulate(
        [
            {"id": "acetic-acid", "amount": 50},
            {"id": "sodium-bicarbonate", "amount": 50},
        ]
    )
    seen = " ".join(result["observations"])
    # Only what dissolves or reacts cools the water: a few degrees, not -38 °C.
    assert 5 < result["vessel"]["temperature_c"] < 22
    assert result["vessel"]["solids"][0]["grams"] > 30
    assert "sits on the bottom" in seen
    assert "-38" not in seen
