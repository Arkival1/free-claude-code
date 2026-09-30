"""The Lab bench: mix, make, build, and test, and keep what was made.

The rules in sim, recipes, materials, and tech give real results. What they
don't cover goes to PubChem (to learn a new chemical) and to a server AI
(to predict a reaction or write a new product formula), always labelled
as a prediction.
"""

import re
from collections.abc import Awaitable, Callable

import httpx
from loguru import logger

from ..jsonish import extract_object
from ..models import LabChemical, LabProject, now_ms
from ..store import StudioStore
from . import chemicals, materials, recipes, tech
from .chemicals import Chemical
from .data import LabData
from .elements import ELEMENTS
from .pubchem import PubChemError, lookup
from .safety import refusal
from .sim import LabError, simulate

Think = Callable[[str, str], Awaitable[str]]
"""Ask the Lab's AI (a server model): (system, prompt) → reply text."""

MAX_PROJECTS = 200

LAB_PROMPT = (
    "You are in the Lab with the user, on the Lab page where they watch the "
    "bench. For anything they want to make, mix, test, or build, use the lab "
    "tool: make for a product or gadget (shampoo, soap, a flashlight), mix to "
    "pour chemicals together and see what really happens, build to power "
    "electronics parts, material to blend and test materials, find to look "
    "something up. The bench animates what the tool makes. Then tell the "
    "user briefly what is inside and what happened, with any safety "
    "warning. Never help make weapons, explosives, drugs, or poisons."
)

PREDICT_SYSTEM = (
    "You are a careful chemist predicting what happens in a school or "
    "hobby lab. Base it on real chemistry. Reply with one JSON object only: "
    '{"happens": "what you would see, 1-3 sentences", "equation": '
    '"balanced equation or empty", "colour": "#rrggbb of the liquid after", '
    '"gas": "gas given off or empty", "precipitate": "solid formed or empty", '
    '"temperature_change_c": number, "hazards": ["short warnings"]}. If '
    "nothing reacts, say so."
)

PRODUCT_SYSTEM = (
    "You are a product formulator. Write a real, safe, working formula for "
    "the product using ingredients from the shelf list (use their ids). "
    "Percentages are by mass and add up to 100. Reply with one JSON object "
    'only: {"name": "...", "container": "bottle|pump|tube|jar|bar|spray|'
    'candle|ball|flask", "batch_g": 250, "ph": "...", "ingredients": '
    '[{"id": "shelf id", "percent": 12.5, "purpose": "why it is there"}], '
    '"steps": ["..."], "safety": "..."}'
)


class LabBench:
    def __init__(
        self,
        store: StudioStore,
        *,
        think: Think | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._store = store
        self._think = think
        self._transport = transport

    # ------------------------------------------------------------ shelves

    async def learned(self) -> dict[str, Chemical]:
        found: dict[str, Chemical] = {}
        for row in await self._store.find(LabChemical, order_by="created_at ASC"):
            chemical = _learned_chemical(row)
            for key in (row.id, row.name.lower(), row.formula.lower()):
                if key:
                    found.setdefault(key, chemical)
        return found

    async def catalogue(self) -> LabData:
        learned = {
            chemical.id: chemical for chemical in (await self.learned()).values()
        }
        shelf = [chemical.view() for chemical in chemicals.CHEMICALS]
        for chemical in learned.values():
            view = chemical.view()
            view["source"] = "pubchem"
            shelf.append(view)
        return {
            "elements": [element.view() for element in ELEMENTS],
            "chemicals": shelf,
            "materials": [material.view() for material in materials.MATERIALS],
            "parts": [part.view() for part in tech.PARTS],
            **recipes.catalogue(),
        }

    async def lookup(self, name: str) -> LabData:
        """A chemical from the shelf, or learned from PubChem and kept."""
        blocked = refusal(name)
        if blocked:
            raise LabError(blocked)
        known = chemicals.resolve(name)
        if known is not None:
            return known.view()
        learned = await self.learned()
        if name.strip().lower() in learned:
            view = learned[name.strip().lower()].view()
            view["source"] = "pubchem"
            return view
        try:
            found = await lookup(name, transport=self._transport)
        except PubChemError as error:
            raise LabError(str(error)) from error
        if found is None:
            raise LabError(f"PubChem doesn't know {name!r}. Check the spelling?")
        row = LabChemical(
            name=str(found["name"]),
            formula=str(found["formula"]),
            molar_mass=float(str(found["molar_mass"] or 0)),
            iupac=str(found["iupac"]),
            cid=int(str(found["cid"] or 0)),
            note=f"Looked up on PubChem as {name!r}.",
        )
        await self._store.put(row)
        view = _learned_chemical(row).view()
        view["source"] = "pubchem"
        view["url"] = found["url"]
        return view

    # ------------------------------------------------------------ doing things

    async def mix(
        self,
        items: list[LabData],
        *,
        heat: bool = False,
        flame: bool = False,
        predict: bool = True,
    ) -> LabData:
        """Mix things in a beaker: the rules first, then PubChem and the AI."""
        for item in items:
            blocked = refusal(str(item.get("id") or item.get("name") or ""))
            if blocked:
                raise LabError(blocked)
        clean = [dict(item) for item in items]
        extra = await self.learned()
        result = simulate(clean, heat=heat, flame=flame, extra=extra)
        unknown = list(result["unknown"])
        if unknown:
            for name in unknown:
                try:
                    await self.lookup(str(name))
                except LabError as error:
                    logger.info("Lab: couldn't learn {}: {}", name, error)
            extra = await self.learned()
            result = simulate(clean, heat=heat, flame=flame, extra=extra)
        new_ones = [
            str(item.get("id") or item.get("name") or "")
            for item in clean
            if str(item.get("id") or item.get("name") or "").lower() in extra
            and chemicals.resolve(str(item.get("id") or item.get("name") or "")) is None
        ]
        if (
            predict
            and self._think
            and (new_ones or result["unknown"])
            and not result["reactions"]
        ):
            prediction = await self._predict(clean, heat=heat, flame=flame)
            if prediction:
                result["prediction"] = prediction
                colour = str(prediction.get("colour") or "")
                if re.fullmatch(r"#[0-9a-fA-F]{6}", colour):
                    vessel = result["vessel"]
                    assert isinstance(vessel, dict)
                    vessel["colour"] = colour
                    vessel["opacity"] = 0.6
                result["summary"] = f"AI prediction: {prediction.get('happens', '')}"
                result["source"] = "rules+ai"
        return result

    async def _predict(
        self, items: list[LabData], *, heat: bool, flame: bool
    ) -> LabData:
        assert self._think is not None
        listed = "\n".join(
            f"- {item.get('amount', '')} {item.get('unit', '')} {item.get('id') or item.get('name')}".replace(
                "  ", " "
            )
            for item in items
        )
        conditions = ", heated" if heat else ""
        conditions += ", held in a flame" if flame else ""
        try:
            text = await self._think(
                PREDICT_SYSTEM, f"Mixed together at 20 °C{conditions}:\n{listed}"
            )
        except Exception as error:
            logger.info("Lab: prediction failed: {}", error)
            return {}
        data = extract_object(text)
        if not data:
            return {"happens": text.strip()[:600], "source": "ai"}
        data["source"] = "ai"
        return data

    async def make(
        self, request: str, *, made_by: str = "You", batch_g: float | None = None
    ) -> LabData:
        """Make a product or a gadget from a plain request ('make shampoo')."""
        blocked = refusal(request)
        if blocked:
            raise LabError(blocked)
        key = recipes.product_key(request)
        if key:
            product = recipes.template_product(key, batch_g=batch_g)
            reaction = product.get("reaction")
            if isinstance(reaction, list) and reaction:
                product["test"] = simulate(
                    [
                        {"id": item, "amount": 20 if item != "borax" else 1}
                        for item in reaction
                    ]
                )
            return await self._save(
                str(product["name"]), "product", request, product, made_by
            )
        build = recipes.build_key(request)
        if build:
            return await self.build_template(build, request=request, made_by=made_by)
        if self._think is None:
            raise LabError(
                "No recipe for that yet, and the Lab's AI isn't set up. Try: "
                + ", ".join(
                    str(entry["name"]).lower()
                    for entry in list(recipes.PRODUCTS.values())[:6]
                )
                + "."
            )
        shelf = ", ".join(chemical.id for chemical in chemicals.CHEMICALS)
        try:
            text = await self._think(
                PRODUCT_SYSTEM, f"Make: {request}\n\nShelf ids: {shelf}"
            )
        except Exception as error:
            raise LabError(f"The Lab's AI couldn't write a formula: {error}") from error
        data = extract_object(text)
        rows = data.get("ingredients")
        if not isinstance(rows, list) or not rows:
            raise LabError(
                "The Lab's AI didn't give a usable formula. Try asking again."
            )
        product = recipes.build_product(
            str(data.get("name") or request.strip().capitalize()),
            [row for row in rows if isinstance(row, dict)],
            batch_g=_number(data.get("batch_g"), 250),
            container=str(data.get("container") or "bottle"),
            steps=[str(step) for step in data.get("steps", []) if isinstance(step, str)]
            if isinstance(data.get("steps"), list)
            else [],
            ph=str(data.get("ph") or ""),
            safety=str(data.get("safety") or ""),
            source="ai",
        )
        return await self._save(
            str(product["name"]), "product", request, product, made_by
        )

    async def build_template(
        self, key: str, *, request: str = "", made_by: str = "You"
    ) -> LabData:
        entry = recipes.BUILDS[key]
        parts = [{"id": part, "count": count} for part, count in entry["parts"]]
        result = tech.simulate_build(parts, series=bool(entry.get("series", True)))
        result["name"] = entry["name"]
        result["steps"] = list(entry.get("steps", ()))
        result["bill"] = parts
        result["series"] = bool(entry.get("series", True))
        result["template"] = key
        return await self._save(
            str(entry["name"]), "build", request or str(entry["name"]), result, made_by
        )

    async def build(
        self,
        parts: list[LabData],
        *,
        series: bool = True,
        name: str = "",
        save: bool = False,
        made_by: str = "You",
    ) -> LabData:
        blocked = refusal(name)
        if blocked:
            raise LabError(blocked)
        try:
            result = tech.simulate_build(parts, series=series)
        except ValueError as error:
            raise LabError(str(error)) from error
        result["name"] = name or "My build"
        result["bill"] = parts
        result["series"] = series
        if save:
            return await self._save(str(result["name"]), "build", name, result, made_by)
        return result

    async def material(
        self,
        parts: list[LabData],
        *,
        name: str = "",
        save: bool = False,
        made_by: str = "You",
    ) -> LabData:
        try:
            result = materials.blend(parts)
        except ValueError as error:
            raise LabError(str(error)) from error
        if name:
            material = result["material"]
            assert isinstance(material, dict)
            material["name"] = name
        if save:
            material = result["material"]
            assert isinstance(material, dict)
            return await self._save(
                str(material["name"]), "material", name, result, made_by
            )
        return result

    # ------------------------------------------------------------ projects

    async def _save(
        self, name: str, kind: str, request: str, data: LabData, made_by: str
    ) -> LabData:
        project = LabProject(
            name=name, kind=kind, request=request, data=data, made_by=made_by
        )
        await self._store.put(project)
        old = await self._store.find(LabProject, order_by="created_at DESC")
        for extra in old[MAX_PROJECTS:]:
            await self._store.delete(LabProject, extra.id)
        return project_view(project)

    async def save(
        self,
        *,
        name: str,
        kind: str,
        data: LabData,
        request: str = "",
        made_by: str = "You",
    ) -> LabData:
        if kind not in {"mix", "product", "material", "build"}:
            raise LabError("Save a mix, product, material, or build.")
        return await self._save(
            name.strip() or "Untitled", kind, request, dict(data), made_by
        )

    async def projects(self) -> list[LabData]:
        rows = await self._store.find(LabProject, order_by="created_at DESC")
        return [project_view(row, full=False) for row in rows]

    async def project(self, project_id: str) -> LabData:
        return project_view(await self._store.require(LabProject, project_id))

    async def delete(self, project_id: str) -> bool:
        return await self._store.delete(LabProject, project_id)

    async def rename(self, project_id: str, name: str) -> LabData:
        row = await self._store.require(LabProject, project_id)
        updated = row.model_copy(
            update={"name": name.strip() or row.name, "updated_at": now_ms()}
        )
        await self._store.put(updated)
        return project_view(updated)


def project_view(project: LabProject, *, full: bool = True) -> LabData:
    view: LabData = {
        "id": project.id,
        "name": project.name,
        "kind": project.kind,
        "request": project.request,
        "made_by": project.made_by,
        "created_at": project.created_at,
    }
    if full:
        view["data"] = project.data
    else:
        colour = project.data.get("colour")
        vessel = project.data.get("vessel")
        if not colour and isinstance(vessel, dict):
            colour = vessel.get("colour")
        view["colour"] = colour if isinstance(colour, str) else ""
    return view


def _learned_chemical(row: LabChemical) -> Chemical:
    return Chemical(
        id=row.id,
        name=row.name,
        formula=row.formula,
        kind="compound",
        state=row.state,
        colour=row.colour,
        aliases=(row.name.lower(), row.iupac.lower())
        if row.iupac
        else (row.name.lower(),),
        note=row.note or "From PubChem: the Lab has no reaction rules for it yet.",
    )


def _number(value: object, default: float) -> float:
    if (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and 0 < value <= 100_000
    ):
        return float(value)
    return default
