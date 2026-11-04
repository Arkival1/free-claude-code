"""FCC Phone's Web kit: websites put together from polished sections on one
design system, previewed live at phone and computer size, started as a
project that passes the project checks, and the web_kit tool the AI uses."""

from playwright.sync_api import ConsoleMessage, Page, expect

from .test_fcc_phone import go, open_phone


def test_the_web_kit_room_builds_a_site_you_can_start(
    page: Page, admin_base_url: str
) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def console_error(message: ConsoleMessage) -> None:
        if message.type == "error" and "fonts.g" not in message.text:
            errors.append(message.text)

    page.on("console", console_error)
    open_phone(page, admin_base_url)
    go(page, "lab/web")
    expect(page.locator("section.card h2", has_text="Web kit")).to_be_visible()
    preview = page.frame_locator("iframe.web-preview")
    expect(preview.locator("h1").first).to_have_text(
        "Fresh every morning, right on your corner"
    )
    # Another starting point, look and theme; reorder, remove and add sections.
    page.get_by_role("button", name="Product launch").click()
    expect(preview.locator("h1").first).to_have_text("The simplest way to get it done")
    page.get_by_role("button", name="Forest").click()
    page.get_by_label("Theme").select_option("dark")
    expect(preview.locator("html[data-theme='dark']")).to_have_count(1)
    page.get_by_role("button", name="Move Bento grid up").click()
    page.get_by_role("button", name="Remove Numbers").click()
    page.locator("summary", has_text="Add a section").click()
    page.get_by_role("button", name="+ Menu / price list").click()
    sections = page.evaluate("() => window.fccPhone.state.webKit.sections")
    assert sections.index("bento") < sections.index("logos")
    assert "stats" not in sections
    assert sections.index("menu") < sections.index("footer-columns")
    page.get_by_role("button", name="Computer").click()
    expect(page.locator(".web-frame[data-width='computer']")).to_have_count(1)

    page.get_by_role("button", name="Start this site").click()
    page.get_by_label("The site's name").fill("Harbour Café")
    page.get_by_label("One line about it").fill("Coffee on the harbour since 2014")
    page.get_by_role("button", name="Start it").click()
    expect(page.get_by_role("heading", name="Harbour Café")).to_be_visible()
    result = page.evaluate(
        """async () => {
            const { runTool } = await import('./js/tools.js');
            const project = window.fccPhone.state.projects.find((p) => p.name === 'Harbour Café');
            const builder = window.fccPhone.state.agents.find((a) => a.id === 'builder');
            const ctx = { project, depth: 0, chain: [], built: new Set() };
            return {
                files: Object.keys(project.files).sort(),
                index: project.files['index.html'],
                styles: project.files['styles.css'],
                checked: await runTool(builder, { name: 'check_project', arguments: {} }, ctx),
            };
        }"""
    )
    assert result["files"] == ["index.html", "kit/kit.css", "kit/kit.js", "styles.css"]
    assert "<title>Harbour Café</title>" in result["index"]
    assert 'content="Coffee on the harbour since 2014"' in result["index"]
    assert 'data-theme="dark"' in result["index"]
    assert "--brand: #166534" in result["styles"]
    assert "FCCNAME" not in result["index"]
    # A fresh kit site isn't finished: its sample words and stand-in
    # pictures are listed until real ones go in.
    assert "the Web kit's sample line" in result["checked"]
    assert "gradient stand-ins" in result["checked"]
    expect(page.frame_locator("iframe.preview").locator("h1").first).to_have_text(
        "The simplest way to get it done"
    )
    assert errors == [], errors


def test_the_ai_builds_websites_with_the_web_kit_tool(
    page: Page, admin_base_url: str
) -> None:
    open_phone(page, admin_base_url)
    result = page.evaluate(
        """async () => {
            const { runTool } = await import('./js/tools.js');
            const { createProject, writeFile } = await import('./js/projects.js');
            const builder = window.fccPhone.state.agents.find((a) => a.id === 'builder');
            const project = await createProject('Ridge Plumbing');
            const ctx = { project, depth: 0, chain: [], built: new Set() };
            const tool = (args, extra = {}) => runTool(builder, { name: 'web_kit', arguments: args }, { ...ctx, ...extra });
            return {
                tools: builder.tools,
                guide: await tool({ action: 'guide' }),
                list: await tool({ action: 'list' }),
                section: await tool({ action: 'section', id: 'pricing' }),
                helper: await tool({ action: 'page', recipe: 'service' }, { partsOnly: true }),
                filesBeforePage: Object.keys(project.files),
                page: await tool({ action: 'page', recipe: 'service', look: 'ocean', title: 'Ridge Plumbing' }),
                files: Object.keys(project.files).sort(),
                index: project.files['index.html'],
                checked: await runTool(builder, { name: 'check_project', arguments: {} }, ctx),
                finished: await (async () => {
                    // The AI writes the real words and photos: then it passes.
                    const { SAMPLE_TEXT } = await import('./web/sections.js');
                    let html = project.files['index.html'];
                    for (const line of SAMPLE_TEXT) html = html.replaceAll(line, 'Ridge Plumbing fixes leaks fast');
                    html = html.replaceAll('hello@example.com', 'jobs@ridgeplumbing.com.au');
                    html = html.replace(/<div class="art([^"]*)" role="img" aria-label="([^"]*)"([^>]*)><\\/div>/g, '<div class="art$1"$3><img class="photo" src="https://images.ridgeplumbing.com.au/van.jpg" alt="$2"></div>');
                    await writeFile(project, 'index.html', html, 'Builder');
                    return runTool(builder, { name: 'check_project', arguments: {} }, ctx);
                })(),
            };
        }"""
    )
    assert "web_kit" in result["tools"]
    assert "Mobile first" in result["guide"] and "Hierarchy" in result["guide"]
    assert "hero-split" in result["list"] and "Recipes:" in result["list"]
    assert 'class="pricing"' in result["section"]
    assert "only under parts/" in result["helper"]
    assert result["filesBeforePage"] == []
    assert result["page"].startswith("Built Ridge Plumbing from the Web kit")
    assert result["files"] == ["index.html", "kit/kit.css", "kit/kit.js", "styles.css"]
    assert result["index"].index('class="nav') < result["index"].index("<main")
    assert result["index"].index("</main>") < result["index"].index('class="footer')
    assert "hello@example.com" in result["checked"]
    assert "gradient stand-ins" in result["checked"]
    assert result["finished"] == "Ridge Plumbing passed every check.", result[
        "finished"
    ]


def test_web_kit_edge_cases_from_people_and_models(
    page: Page, admin_base_url: str
) -> None:
    open_phone(page, admin_base_url)
    result = page.evaluate(
        """async () => {
            const { runTool } = await import('./js/tools.js');
            const { createProject, writeFile, checkProject } = await import('./js/projects.js');
            const { pageHtml } = await import('./web/sections.js');
            const builder = window.fccPhone.state.agents.find((a) => a.id === 'builder');
            const project = await createProject('Cash $& Carry');
            const ctx = { project, depth: 0, chain: [], built: new Set() };
            const tool = (args) => runTool(builder, { name: 'web_kit', arguments: args }, ctx);
            const out = {};
            out.first = await tool({ action: 'page', sections: ['hero-center', 'constructor', 'faq'], look: 'toString' });
            out.index = project.files['index.html'];
            out.styles = project.files['styles.css'];
            // A second page call never overwrites the work without replace.
            await writeFile(project, 'index.html', '<h1>My own words</h1>', 'Builder');
            out.again = await tool({ action: 'page', recipe: 'shop' });
            out.kept = project.files['index.html'];
            out.replaced = await tool({ action: 'page', recipe: 'shop', replace: true });
            // Stand-ins: an empty art div is flagged whichever attribute comes
            // first; one with a photo inside is a finished picture.
            const check = async (html) => {
                await writeFile(project, 'index.html', html, 'Builder');
                return checkProject(project).join(' ');
            };
            out.flagged = await check('<!doctype html><html><head><title>A</title></head><body><div role="img" class="art art-2" aria-label="Van"></div></body></html>');
            out.photo = await check('<!doctype html><html><head><title>A</title></head><body><div class="art" role="img" aria-label="Van"><img class="photo" src="https://x.example/van.jpg" alt="Van"></div></body></html>');
            out.realName = await check('<!doctype html><html><head><title>A</title></head><body><h1>Northwind Traders</h1><p>Ava Park runs it.</p></body></html>');
            out.noScript = pageHtml({ title: 'Plain', sections: ['hero-center'] }).replace('<script>document.documentElement.classList.add("js")</script>', '').replace('<script src="kit/kit.js" defer></script>', '');
            return out;
        }"""
    )
    assert "Cash $&amp; Carry" in result["index"] and "FCCNAME" not in result["index"]
    assert (
        "Not in the kit, so left out: section constructor, look toString"
        in result["first"]
    )
    assert "--brand: #2563eb" in result["styles"]
    assert "already has an index.html: nothing was changed" in result["again"]
    assert result["kept"] == "<h1>My own words</h1>"
    assert result["replaced"].startswith("Built Cash $& Carry from the Web kit")
    assert "gradient stand-ins" in result["flagged"]
    assert "gradient stand-ins" not in result["photo"]
    assert "sample line" not in result["realName"]
    # Without any script the revealed sections still show.
    page.set_content(
        result["no_script"] if "no_script" in result else result["noScript"]
    )
    page.add_style_tag(path="src/free_claude_code/api/phone_static/web/kit.css")
    opacity = page.evaluate(
        "() => getComputedStyle(document.querySelector('[data-reveal]')).opacity"
    )
    assert opacity == "1"
