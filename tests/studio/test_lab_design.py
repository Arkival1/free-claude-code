"""Lab designs: technology in its real materials, checked against physics,
and creations kept as parts for other designs."""

import httpx
import pytest

from free_claude_code.studio.lab.bench import LabBench
from free_claude_code.studio.lab.design import check, finish
from free_claude_code.studio.lab.materials import find
from free_claude_code.studio.lab.sim import LabError
from free_claude_code.studio.llm import LLMReply
from tests.api.support import create_test_app

from .conftest import tool_reply

CART = [
    {
        "name": "Frame",
        "material": "steel",
        "shape": "plate",
        "size_mm": [200, 3, 150],
        "role": "structure",
        "carries_kg": 2,
    },
    {
        "name": "Shell",
        "material": "abs",
        "shape": "box",
        "size_mm": [210, 60, 160],
        "role": "casing",
    },
    {"name": "Brain", "part": "arduino", "material": "fr4", "shape": "board"},
    {"name": "Battery", "part": "18650", "count": 2},
    {"name": "Motor", "part": "motor", "role": "moving", "count": 2},
    {"name": "Wiring", "material": "copper", "shape": "wire", "size_mm": [0.8, 600]},
]


def test_each_component_is_drawn_in_its_material_and_weighed():
    result = check(CART, name="Cart")
    frame = result["components"][0]
    assert frame["material"]["id"] == "steel" and frame["material"]["finish"] == "metal"
    # 200 x 3 x 150 mm of steel (7.85 g/cm³) is about 707 g.
    assert frame["mass_g"] == pytest.approx(706.5, rel=0.01)
    assert result["components"][2]["material"]["finish"] == "board"
    assert {row["id"] for row in result["materials"]} >= {"steel", "copper"}
    assert sum(row["share_pct"] for row in result["materials"]) == pytest.approx(
        100, abs=0.5
    )
    assert all(row["how"] for row in result["components"])


def test_the_electronics_run_on_the_circuit_bench():
    result = check(CART)
    assert result["electronics"] is not None
    assert any(row["name"] == "Electronics" for row in result["checks"])
    assert result["components"][3]["state"] in {"ok", "on", "power", ""}


def test_a_thin_member_under_load_is_flagged():
    weak = [
        {
            "name": "Thin rod",
            "material": "pla",
            "shape": "rod",
            "size_mm": [1, 100],
            "role": "structure",
            "carries_kg": 20,
        }
    ]
    result = check(weak)
    [row] = result["components"]
    assert row["verdict"] == "breaks" and row["safety_factor"] < 1
    assert result["verdict"] == "Needs changes" and result["warnings"]
    strong = check([{**weak[0], "material": "steel", "size_mm": [20, 100]}])
    assert strong["components"][0]["verdict"] == "strong"


def test_iron_outdoors_rusts_and_mixed_metals_corrode():
    lamp = [
        {"name": "Post", "material": "iron", "shape": "rod", "size_mm": [20, 600]},
        {
            "name": "Screws",
            "material": "brass",
            "shape": "rod",
            "size_mm": [3, 12],
            "count": 4,
        },
    ]
    dry = check(lamp, wet=False)
    wet = check(lamp, wet=True)
    assert not dry["warnings"]
    assert any("rusts" in text for text in wet["warnings"])
    assert any("corrode each other" in text for text in wet["warnings"])
    assert wet["components"][0]["rusting"] is True


def test_a_hot_plastic_case_and_a_metal_case_are_called_out():
    heater = [
        {
            "name": "Case",
            "material": "pla",
            "shape": "box",
            "size_mm": [20, 20, 20],
            "role": "casing",
        },
        {"name": "Power", "part": "usb"},
        {"name": "Lights", "part": "led-strip", "count": 3},
    ]
    result = check(heater)
    heat = next(row for row in result["checks"] if row["name"] == "Heat")
    assert heat["ok"] is False
    metal = check([{**heater[0], "material": "aluminium"}, *heater[1:]])
    assert any("conducts electricity" in note for note in metal["notes"])


def test_unknown_materials_and_parts_are_refused_not_guessed():
    with pytest.raises(LabError, match="No material"):
        check([{"name": "X", "material": "unobtainium"}])
    with pytest.raises(LabError, match="No electronics part"):
        check([{"name": "X", "part": "flux-capacitor"}])
    with pytest.raises(LabError):
        check([])


def test_circuit_board_material_exists():
    board = find("fr4")
    assert board is not None and finish(board) == "board"


@pytest.mark.asyncio
async def test_designs_are_kept_copied_and_reused_as_parts(store):
    bench = LabBench(store)
    saved = await bench.design(CART, name="Cart", save=True)
    assert saved["kind"] == "design"
    kept = await bench.keep_part("Drive unit", project_id=saved["id"])
    assert kept["count"] == len(CART)
    [listed] = await bench.parts_kept()
    assert listed["name"] == "Drive unit"
    # The kept part goes into another design (twice), opened into its parts.
    bigger = await bench.design(
        [
            {"assembly": kept["id"], "count": 2},
            {
                "name": "Deck",
                "material": "wood-oak",
                "shape": "plate",
                "size_mm": [400, 10, 300],
            },
        ],
        name="Two carts on a deck",
    )
    frames = [row for row in bigger["components"] if row["name"] == "Frame"]
    assert frames and frames[0]["count"] == 2
    assert bigger["mass_g"] > saved["data"]["mass_g"]
    copy = await bench.copy(saved["id"])
    assert copy["name"] == "Copy of Cart" and copy["kind"] == "design"
    assert await bench.delete_part(kept["id"]) is True
    with pytest.raises(LabError):
        await bench.design([{"assembly": kept["id"]}])


@pytest.mark.asyncio
async def test_designs_through_the_app(make_studio):
    studio, _ = make_studio([])
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        checked = await client.post(
            "/studio/api/lab/design", json={"components": CART, "name": "Cart"}
        )
        assert checked.status_code == 200, checked.text
        assert checked.json()["components"][0]["material"]["finish"] == "metal"
        saved = (
            await client.post(
                "/studio/api/lab/design",
                json={"components": CART, "name": "Cart", "save": True},
            )
        ).json()
        assert saved["kind"] == "design"
        kept = (
            await client.post(
                "/studio/api/lab/library",
                json={"project_id": saved["id"], "name": "Drive unit"},
            )
        ).json()
        listed = (await client.get("/studio/api/lab/library")).json()["parts"]
        assert [part["name"] for part in listed] == ["Drive unit"]
        copied = (
            await client.post(f"/studio/api/lab/projects/{saved['id']}/copy")
        ).json()
        assert copied["name"] == "Copy of Cart"
        bad = await client.post(
            "/studio/api/lab/design",
            json={"components": [{"name": "X", "material": "unobtainium"}]},
        )
        assert bad.status_code == 400
        gone = await client.delete(f"/studio/api/lab/library/{kept['id']}")
        assert gone.json() == {"deleted": True}


@pytest.mark.asyncio
async def test_jarvis_designs_in_steel_from_the_lab_chat(make_studio):
    turns = iter(
        [
            tool_reply(
                "lab",
                {
                    "action": "design",
                    "request": "Steel robot cart",
                    "components": CART,
                },
            ),
            LLMReply(text="Your steel cart is on the Design bench."),
        ]
    )

    def respond(system: str, prompt: str):
        if "running notes" in system:
            return LLMReply(text="Goal:\n- Cart")
        return next(turns, LLMReply(text="Done."))

    studio, _ = make_studio(respond)
    await studio.ensure_defaults()
    await studio.lab_say(
        "hey jarvis design a robot cart with a steel frame", background=False
    )
    console = await studio.lab_console()
    tool = next(m for m in console["messages"] if m["role"] == "tool")
    assert tool["data"]["action"] == "design" and "Mild steel" in tool["text"]
    project = await studio.lab.project(tool["data"]["project_id"])
    assert project["kind"] == "design"
    assert project["data"]["components"][0]["material"]["id"] == "steel"
