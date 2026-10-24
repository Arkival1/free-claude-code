"""Look any chemical up on PubChem, the free US government database."""

from urllib.parse import quote

import httpx

from .formula import FormulaError, molar_mass

PUBCHEM = (
    "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{name}/property/"
    "MolecularFormula,MolecularWeight,IUPACName,Title/JSON"
)


class PubChemError(RuntimeError):
    """PubChem couldn't be reached or doesn't know the name."""


async def lookup(
    name: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> dict[str, object] | None:
    """Formula, molar mass, and proper name for a chemical, or None if unknown."""
    wanted = name.strip()
    if not wanted or len(wanted) > 120:
        return None
    url = PUBCHEM.format(name=quote(wanted, safe=""))
    async with httpx.AsyncClient(timeout=12, transport=transport) as client:
        try:
            response = await client.get(url)
        except httpx.HTTPError as error:
            raise PubChemError(f"PubChem couldn't be reached: {error}") from error
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise PubChemError(f"PubChem answered {response.status_code}.")
    try:
        rows = response.json()["PropertyTable"]["Properties"]
        row = rows[0]
    except ValueError, KeyError, IndexError, TypeError:
        return None
    formula = str(row.get("MolecularFormula") or "")
    try:
        mass = float(row.get("MolecularWeight") or 0) or molar_mass(formula)
    except FormulaError, KeyError, ValueError:
        mass = 0.0
    return {
        "cid": row.get("CID"),
        "name": str(row.get("Title") or wanted),
        "iupac": str(row.get("IUPACName") or ""),
        "formula": formula,
        "molar_mass": round(mass, 3),
        "source": "pubchem",
        "url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{row.get('CID')}",
    }
