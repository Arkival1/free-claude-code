"""Jarvis learns (#practice): his courses, skills waiting for the user's OK
(an OK puts the skill into his lessons), and his notes on what he can't do."""

from playwright.sync_api import Page, expect

from .test_fcc_phone import open_phone


def test_skills_wait_for_the_users_ok_and_notes_show(
    page: Page, admin_base_url: str
) -> None:
    open_phone(page, admin_base_url)
    page.evaluate(
        """async () => {
            const { store } = await import('./js/store.js');
            await store.set('practice', {
                progress: { python: { next: 2, passed: [1], stuck: [2] } },
                skills: [{ id: 's1', lang: 'python', lesson: 1, topic: 'variables, types and f-strings', title: 'Format numbers with f-strings', note: 'Use f"{x:.2f}" for two decimals; test the edge cases.', folder: '/root/learn/python/01', status: 'waiting', at: Date.now() }],
                notes: [{ id: 'n1', lang: 'python', lesson: 2, topic: 'lists, dicts and comprehensions', text: 'Nested comprehensions still confuse me.', at: Date.now() }],
            });
        }"""
    )
    page.goto(f"{admin_base_url}/phone/?look=hud#practice")
    expect(page.get_by_role("heading", name="Jarvis learns to code")).to_be_visible()
    expect(page.get_by_text("1 of")).to_be_visible()
    expect(page.get_by_text("Nested comprehensions still confuse me.")).to_be_visible()
    expect(page.get_by_role("button", name="▶ Practise")).to_be_visible()
    page.get_by_role("button", name="Approve Format numbers with f-strings").click()
    expect(page.get_by_text("None yet")).to_be_visible()
    lesson = page.evaluate(
        "() => window.fccPhone.state.memories.find((m) => m.kind === 'lesson' && m.text.includes('f-strings'))"
    )
    assert lesson and "Skill (Python)" in lesson["text"], lesson
