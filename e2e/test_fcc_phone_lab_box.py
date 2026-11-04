"""FCC Phone's Lab box: the phone's chemistry and circuit benches give the PC
Lab's answers, the rooms work (benches, blueprints with versions, chips added
to a circuit, the build-your-own-x Library, the Game kit), and Jarvis does a
Lab job himself (he works the bench and saves a blueprint, no other agent)."""

import itertools
import json
import math
import re

from playwright.sync_api import ConsoleMessage, Page, expect

from free_claude_code.studio.lab import chemicals, sim, tech

from .test_fcc_phone import fake_gemini, go, open_phone, say, tool_call, use_gemini


def same(a: object, b: object, path: str = "") -> list[str]:
    """Where two results differ (numbers to a millionth)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return [] if a == b else [f"{path}: {a!r} != {b!r}"]
    if isinstance(a, int | float) and isinstance(b, int | float):
        if math.isinf(a) and math.isinf(b):
            return []
        return [] if abs(a - b) <= 1e-6 + 1e-6 * abs(a) else [f"{path}: {a!r} != {b!r}"]
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return [f"{path}: keys {sorted(set(a) ^ set(b))}"]
        return [
            problem for key in a for problem in same(a[key], b[key], f"{path}.{key}")
        ]
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: {len(a)} items != {len(b)}"]
        return [
            problem
            for index, (x, y) in enumerate(zip(a, b, strict=True))
            for problem in same(x, y, f"{path}[{index}]")
        ]
    return [] if a == b else [f"{path}: {a!r} != {b!r}"]


def run_python(kind: str, items: list[dict], options: dict) -> dict:
    try:
        if kind == "mix":
            return {"got": sim.simulate(items, **options)}
        return {"got": tech.simulate_build(items, **options)}
    except ValueError as error:
        return {"error": str(error)}


def test_the_phone_benches_give_the_pc_labs_answers(
    page: Page, admin_base_url: str
) -> None:
    ids = [chemical.id for chemical in chemicals.CHEMICALS]
    cases: list[tuple[str, list[dict], dict]] = []
    for chemical in ids:
        cases.append(("mix", [{"id": "water"}, {"id": chemical}], {}))
        cases.append(("mix", [{"id": chemical}], {"heat": True}))
        cases.append(
            (
                "mix",
                [{"id": "water", "amount": 50}, {"id": chemical, "amount": 5}],
                {"flame": True},
            )
        )
    cases.extend(
        ("mix", [{"id": a}, {"id": b}], {})
        for a, b in itertools.combinations(ids[::2], 2)
    )
    cases.extend(
        ("mix", [{"name": "hydrochloric acid"}, {"id": symbol}], {})
        for symbol in ["Na", "K", "Mg", "Zn", "Cu", "Ag", "I", "element-fe", "Gold"]
    )
    cases.append(("mix", [{"name": "nothing-like-this"}, {"id": "water"}], {}))
    supplies = [part.id for part in tech.PARTS if part.kind == "power"] + ["solar"]
    for supply in supplies:
        for load in [part.id for part in tech.PARTS]:
            for count, series in ((1, True), (4, False), (3, True)):
                cases.append(
                    (
                        "build",
                        [{"id": supply, "count": count}, {"id": load, "count": 2}],
                        {"series": series, "sun": count != 3},
                    )
                )
    cases.append(("build", [{"id": "led-red"}], {}))
    cases.append(("build", [{"id": "no-such-part"}], {}))
    want = [run_python(kind, items, options) for kind, items, options in cases]
    open_phone(page, admin_base_url)
    got = page.evaluate(
        """async (cases) => {
            const { simulate, simulateBuild } = await import('./lab/science.js');
            return cases.map(([kind, items, options]) => {
                try {
                    const result = kind === 'mix' ? simulate(items, options) : simulateBuild(items, options);
                    return { got: JSON.parse(JSON.stringify(result, (key, value) => value === Infinity ? 'inf' : value)) };
                } catch (error) {
                    return { error: error.message };
                }
            });
        }""",
        [[kind, items, options] for kind, items, options in cases],
    )
    problems = []
    for case, expected, actual in zip(cases, want, got, strict=True):
        expected = json.loads(
            json.dumps(expected, default=str).replace("Infinity", '"inf"')
        )
        if "error" in expected or "error" in actual:
            if expected.get("error") != actual.get("error"):
                problems.append(f"{case}: {expected} vs {actual}")
            continue
        found = same(expected["got"], actual["got"])
        if found:
            problems.append(f"{case}: {found[:3]}")
    assert len(cases) > 3000
    assert problems == [], problems[:10]


def test_the_lab_box_rooms_benches_and_blueprints(
    page: Page, admin_base_url: str
) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def console_error(message: ConsoleMessage) -> None:
        if message.type == "error":
            errors.append(message.text)

    page.on("console", console_error)
    open_phone(page, admin_base_url)
    go(page, "lab")
    page.wait_for_function(
        "() => document.querySelector('.lab-world') && document.querySelector('.lab-world').dataset.ready === 'true'",
        timeout=30000,
    )
    rooms = page.locator(".lab-roombar")
    expect(rooms.get_by_role("button")).to_have_text(
        [
            "Box",
            "Chemistry",
            "Electronics",
            "Blueprints",
            "Library",
            "Web kit",
            "Game kit",
        ]
    )

    # Electronics: a starter build, readings with the resistor's real colours.
    rooms.get_by_role("button", name="Electronics").click()
    expect(page.locator(".lab-where")).to_have_text("Electronics")
    page.get_by_role("button", name="Night light").click()
    expect(page.get_by_role("heading", name="✅ It works")).to_be_visible()
    expect(page.locator(".lab-bands").first).to_have_attribute(
        "aria-label", "Colour bands brown, black, brown, gold"
    )
    # Save it as a chip, change it, and save the change as version 2.
    page.get_by_role("button", name="Save as chip").click()
    page.get_by_label("Blueprint name").fill("Night light")
    page.locator("#sheet").get_by_role("button", name="Save", exact=True).click()
    page.get_by_role("button", name="One less Blue LED").click()
    page.get_by_role("button", name="Save as chip").click()
    page.locator("#sheet").get_by_role(
        "button", name="Save as version 2 of Night light"
    ).click()
    prints = page.evaluate("() => window.fccPhone.state.blueprints")
    assert len(prints) == 1 and prints[0]["kind"] == "chip"
    assert len(prints[0]["versions"]) == 2
    first, second = (version["data"]["parts"] for version in prints[0]["versions"])
    assert {"id": "led-blue", "count": 2} in first and {
        "id": "led-blue",
        "count": 1,
    } in second

    # Blueprints: load version 1 back, then drop the chip into the circuit.
    rooms.get_by_role("button", name="Blueprints").click()
    card = page.locator(".lab-print", has_text="Night light")
    expect(card).to_contain_text("Chip · 2 versions")
    card.locator("summary", has_text="Versions").click()
    card.locator(".lab-row").first.get_by_role("button", name="Load").click()
    parts = page.evaluate("() => window.fccPhone.state.bench.electronics.parts")
    assert {"id": "led-blue", "count": 2} in parts
    rooms.get_by_role("button", name="Blueprints").click()
    page.locator(".lab-print", has_text="Night light").get_by_role(
        "button", name="Add to circuit"
    ).click()
    parts = page.evaluate("() => window.fccPhone.state.bench.electronics.parts")
    assert {"id": "arduino", "count": 2} in parts

    # Chemistry: a starter mix, then a bottle from the shelf search.
    rooms.get_by_role("button", name="Chemistry").click()
    page.get_by_role("button", name="Royal blue").click()
    expect(page.get_by_role("heading", name="What happens")).to_be_visible()
    expect(page.locator(".lab-summary")).to_contain_text("complex")
    page.get_by_label("Find a chemical").fill("sodium chloride")
    page.locator(".lab-chips").get_by_role(
        "button", name="Sodium chloride"
    ).first.click()
    items = page.evaluate("() => window.fccPhone.state.bench.chemistry.items")
    assert [item["id"] for item in items][-1] == "sodium-chloride"
    page.get_by_role("button", name="Save as mixture").click()
    page.get_by_label("Blueprint name").fill("Blue salt")
    page.locator("#sheet").get_by_role("button", name="Save", exact=True).click()
    assert page.evaluate("() => window.fccPhone.state.blueprints[0].kind") == "mixture"

    # Library: build-your-own-x by topic, with links.
    rooms.get_by_role("button", name="Library").click()
    page.get_by_role("button", name="Git (7)").click()
    expect(page.get_by_role("heading", name="7 tutorials")).to_be_visible()
    expect(page.locator(".lab-tutorial a").first).to_have_attribute(
        "href", re.compile(r"^https?://")
    )

    # The Game kit room, and back to the box.
    rooms.get_by_role("button", name="Game kit").click()
    expect(page.locator("section.card h2", has_text="Game Lab")).to_be_visible()
    page.get_by_role("button", name="⟵ Lab box").click()
    page.wait_for_function(
        "() => document.querySelector('.lab-world') && document.querySelector('.lab-world').dataset.ready === 'true'",
        timeout=30000,
    )
    assert errors == [], errors


def lab_brain(body: dict) -> dict:
    """Jarvis told to make a torch: he builds it and saves it himself."""
    last = body["messages"][-1]
    said = last.get("content") or ""
    if last["role"] == "user" and "torch" in said:
        return tool_call(
            "lab",
            {
                "action": "circuit",
                "parts": [
                    {"id": "aa", "count": 2},
                    {"id": "led-white"},
                    {"id": "switch"},
                ],
            },
        )
    if last["role"] == "tool" and said.startswith("It works"):
        return tool_call(
            "lab",
            {
                "action": "save",
                "name": "Pocket torch",
                "kind": "chip",
                "notes": "Two AA cells and a white LED.",
            },
        )
    if last["role"] == "tool" and said.startswith("Saved Pocket torch"):
        return say("Built it and saved it as the Pocket torch chip.")
    return say("Hi!")


def test_jarvis_works_the_lab_himself(page: Page, admin_base_url: str) -> None:
    seen = fake_gemini(page, lab_brain)
    open_phone(page, admin_base_url)
    use_gemini(page)
    go(page, "lab")
    page.wait_for_function(
        "() => document.querySelector('.lab-world') && document.querySelector('.lab-world').dataset.ready === 'true'",
        timeout=30000,
    )
    page.get_by_label("Tell Jarvis what to make").fill(
        "Make me a pocket torch and save it as a chip"
    )
    page.locator(".lab-jarvis").get_by_role("button", name="Send").click()
    expect(page.locator(".lab-reply")).to_have_text(
        "Built it and saved it as the Pocket torch chip.", timeout=20000
    )
    state = page.evaluate(
        "() => ({ bench: window.fccPhone.state.bench, prints: window.fccPhone.state.blueprints })"
    )
    assert state["bench"]["electronics"]["result"]["works"] is True
    assert state["prints"][0]["name"] == "Pocket torch"
    assert state["prints"][0]["by"] == "Jarvis"
    assert state["bench"]["jarvis"]["room"] == "blueprints"
    expect(page.locator(".lab-status")).to_contain_text("Jarvis is in Blueprints")
    # He was told to do Lab work himself, and he only used the lab tool.
    system = seen[0]["messages"][0]["content"]
    assert "Don't hand Lab work to another agent" in system
    lab_tool = next(
        tool for tool in seen[0]["tools"] if tool["function"]["name"] == "lab"
    )
    assert (
        "circuit" in lab_tool["function"]["parameters"]["properties"]["action"]["enum"]
    )
    called = [
        call["function"]["name"]
        for body in seen
        for message in body["messages"]
        for call in message.get("tool_calls") or []
    ]
    assert set(called) == {"lab"}


def test_blueprint_versions_are_exact_and_model_arguments_are_safe(
    page: Page, admin_base_url: str
) -> None:
    open_phone(page, admin_base_url)
    result = page.evaluate(
        """async () => {
            const shop = await import('./js/workshop.js');
            const { runTool } = await import('./js/tools.js');
            const jarvis = window.fccPhone.state.agents.find((a) => a.id === 'jarvis');
            const tool = (args) => runTool(jarvis, { name: 'lab', arguments: args }, { depth: 0, chain: [], built: new Set() });
            const out = {};
            await shop.circuit([{ id: 'solar' }, { id: 'fan' }]);
            const fan = await shop.saveBlueprint({ name: 'Solar fan', kind: 'chip' });
            // A partial name never adds a version to another blueprint.
            out.partial = await tool({ action: 'save', id: 'fan', kind: 'chip' });
            out.fanVersions = fan.versions.length;
            // A version of a mixture with no kind given keeps the mixture's kind.
            await tool({ action: 'mix', items: [{ name: 'vinegar', amount: 30 }], heat: 'false' });
            out.heat = window.fccPhone.state.bench.chemistry.heat;
            const brew = await shop.saveBlueprint({ name: 'Sour', kind: 'mixture' });
            await shop.mix([{ id: 'acetic-acid', amount: 30 }, { id: 'sodium-bicarbonate', amount: 3 }]);
            out.versioned = await tool({ action: 'save', id: brew.id });
            out.brewKind = shop.findBlueprint(brew.id).kind;
            // An odd kind falls back to what the benches hold.
            const odd = await shop.saveBlueprint({ name: 'Odd', kind: 'constructor' });
            out.oddKind = odd.kind;
            // A fractional version loads that version, not a crash.
            out.loaded = (await shop.loadBlueprint(brew.id, { version: 1.5 })).version;
            // Past the cap of 30, numbers never shift.
            for (let i = 0; i < 32; i += 1) await shop.saveBlueprint({ kind: 'chip', onto: fan.id });
            const kept = shop.findBlueprint(fan.id);
            out.kept = kept.versions.length;
            out.newest = shop.versionNumber(kept, kept.versions.at(-1));
            out.next = shop.nextVersion(kept);
            out.loadNewest = (await shop.loadBlueprint(fan.id, { version: out.newest })).version;
            // Emptying the board switches the power off.
            await shop.setBoard([{ id: 'aa' }], { powered: true });
            await shop.setBoard([]);
            out.powered = window.fccPhone.state.bench.electronics.powered;
            return out;
        }"""
    )
    assert "No blueprint with the id or name fan" in result["partial"]
    assert result["fanVersions"] == 1
    assert result["heat"] is False
    assert (
        result["versioned"].startswith("Saved Sour (mixture")
        and "version 2" in result["versioned"]
    )
    assert result["brewKind"] == "mixture"
    assert result["oddKind"] == "invention"
    assert result["loaded"] == 1
    assert result["kept"] == 30 and result["newest"] == 33 and result["next"] == 34
    assert result["loadNewest"] == 33
    assert result["powered"] is False


def test_jarvis_lands_on_a_floor_when_a_new_job_comes_mid_ride(
    page: Page, admin_base_url: str
) -> None:
    open_phone(page, admin_base_url)
    go(page, "lab")
    page.wait_for_function(
        "() => document.querySelector('.lab-world') && document.querySelector('.lab-world').world",
        timeout=30000,
    )
    mid_ride = (
        "() => { const at = document.querySelector('.lab-world').world.jarvisAt();"
        " return at.y > 0.4 && at.y < 3.5; }"
    )
    arrived = "() => !document.querySelector('.lab-world').world.jarvisAt().walking"
    world = "document.querySelector('.lab-world').world"

    def send(room: str) -> None:
        page.evaluate(f"() => {world}.jarvisTo('{room}')")

    # Riding down, sent to a room upstairs; then riding up, sent downstairs.
    for first, second, floor_y, settle in (
        ("electronics", "blueprints", 3.6, "chemistry"),
        ("library", "electronics", 0.3, ""),
    ):
        send(first)
        page.wait_for_function(mid_ride, timeout=90000)
        send(second)
        page.wait_for_function(arrived, timeout=90000)
        at = page.evaluate(f"() => {world}.jarvisAt()")
        assert abs(at["y"] - floor_y) < 0.02, at
        if settle:
            send(settle)
            page.wait_for_function(arrived, timeout=90000)
