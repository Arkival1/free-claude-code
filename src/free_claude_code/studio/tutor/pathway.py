"""The path to an electrician's licence in NSW, and where each maths topic fits.

Kept to what the official pages say (read October 2026). Rules and fees
change, so the tutor always points to the source to check before applying.
"""

from free_claude_code.core.json_types import JsonObject

SOURCES: tuple[tuple[str, str], ...] = (
    (
        "NSW Government: electrical licences and certificates",
        "https://www.nsw.gov.au/business-and-economy/licences-and-credentials/building-and-trades-licences-and-credentials/electrical",
    ),
    (
        "TAFE NSW: Certificate III in Electrotechnology Electrician (UEE30820)",
        "https://www.tafensw.edu.au/course-areas/electrotechnology/courses/certificate-iii-in-electrotechnology-electrician--UEE30820-01",
    ),
)

STEPS: tuple[tuple[str, str, str], ...] = (
    (
        "Get an apprenticeship",
        "Find an employer (or a group training organisation) who takes on "
        "electrical apprentices. Many give an aptitude test first: everyday "
        "maths, reading and mechanical reasoning.",
        "entry",
    ),
    (
        "Sign up the apprenticeship",
        "You and your employer register the apprenticeship through an "
        "Apprenticeship Connect Australia provider, and choose a training "
        "provider (an RTO such as TAFE NSW).",
        "algebra",
    ),
    (
        "Do the Certificate III (UEE30820)",
        "The Certificate III in Electrotechnology Electrician, studied while "
        "you work: usually about four years. DC theory comes first, then AC, "
        "then three-phase, machines and installation work.",
        "dc",
    ),
    (
        "Pass the final licensing assessment",
        "At the end of the course you sit the final practical and theory "
        "assessment (often called the capstone): wiring, testing and the "
        "installation calculations.",
        "install",
    ),
    (
        "Apply for your licence",
        "Apply to NSW Fair Trading for a Qualified Supervisor Certificate – "
        "Electrician. To run your own electrical business you also need a "
        "contractor licence.",
        "",
    ),
)

NOTE = (
    "Requirements change: check the NSW Government and TAFE NSW pages before "
    "you apply. Values from Australian Standards tables are given in the "
    "questions; on the job, look them up in AS/NZS 3000 and AS/NZS 3008."
)


def pathway() -> JsonObject:
    return {
        "steps": [
            {"title": title, "detail": detail, "stage": stage}
            for title, detail, stage in STEPS
        ],
        "sources": [{"title": title, "url": url} for title, url in SOURCES],
        "note": NOTE,
    }
