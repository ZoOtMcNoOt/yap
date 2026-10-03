import { expect, test, type Page } from "@playwright/test";
import { installProposalInspectionBridge, proposalReference } from "./connection-proposal-bridge";
const article = (page: Page) => page.getByRole("article", {name:"Saved connection proposal"});
const button = (page: Page) => page.getByRole("button", {name:"Export review package…", exact:true});
async function control(page: Page, method: string, value?: unknown) {
  await page.evaluate(({method,value}) => (globalThis as any).__proposalInspection[method](value), {method,value});
}
async function journey(page: Page, method: string, ...values: Array<string | boolean>) {
  await page.evaluate(({method,values}) => (globalThis as any).__knowledgeJourney[method](...values), {method,values});
}
async function enter(page: Page, reference = proposalReference) {
  await installProposalInspectionBridge(page);
  await page.goto("/");
  await page.getByRole("button", {name:"Knowledge",exact:true}).click();
  await page.getByRole("tab", {name:"Review proposals",exact:true}).click();
  await expect(button(page)).toHaveCount(0);
  await page.getByRole("button", {name:"Load saved proposals",exact:true}).click();
  await page.getByRole("button", {name:`Open saved proposal ${reference}`,exact:true}).click();
  await expect(article(page)).toBeVisible();
}
for (const width of [360,720,1440])
  test(`explicit keyboard export and long saved paths fit ${width}px`, async ({page}) => {
    await page.setViewportSize({width,height:900});
    await enter(page);
    const path = `/review/${"source-bound-review-".repeat(20)}café.json`;
    await control(page,"exportResult",{status:"saved",path});
    await button(page).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByText("Review package saved. Take it into your organization's Git review workflow.",{exact:true})).toBeVisible();
    await expect(article(page).getByText("Proposed · Requires human review")).toBeVisible();
    await expect(button(page)).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({path:test.info().outputPath("review-export-saved.png")});
    await page.getByText("Saved file location",{exact:true}).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByText(path,{exact:true})).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({path:test.info().outputPath("review-export-location.png")});
    const calls = await page.evaluate(() => (globalThis as any).__proposalInspection.calls);
    expect(calls.filter((call:any) => call.command === "export_connection_review_package").map((call:any) => call.args))
      .toEqual([{proposalId:proposalReference,generationSha256:"a".repeat(64),authorityRevision:"1"}]);
    expect(calls.some((call:any) => call.args.request?.action === "discard")).toBe(false);
    expect(await page.evaluate(() => (globalThis as any).__knowledgeJourney.mutations)).toEqual([]);
  });

test("picker cancellation preserves the proposal and allows an explicit retry",async({page}) => {
  await enter(page);
  await control(page,"exportResult",{status:"cancelled"});
  await button(page).click();
  await expect(page.getByText(/Review export cancelled/)).toBeVisible();
  await expect(article(page)).toBeVisible();
  await expect(button(page)).toBeEnabled();
  await control(page,"exportResult",{status:"saved",path:"/review/retry.json"});
  await button(page).click();
  await expect(page.getByText(/Review package saved\./)).toBeVisible();
  await page.getByText("Saved file location",{exact:true}).click();
  await expect(page.getByText("/review/retry.json",{exact:true})).toBeVisible();
});
for (const [code,message] of [
  ["destinationExists",/That file already exists/], ["destination",/Choose a new .json file/],
  ["busy",/Finish the current read or export/], ["exportUnconfirmed",/It may have saved a file/],
])
  test(`${code} explains recovery without claiming a saved or cancelled export`,async({page}) => {
  await enter(page);
  await control(page,"exportMode",code);
  await button(page).click();
  await expect(page.getByText(message)).toBeVisible();
  await expect(page.getByText(/Review package saved\.|Review export cancelled/)).toHaveCount(0);
  await expect(article(page)).toBeVisible();
  await page.getByRole("button",{name:"Search current sources",exact:true}).click();
  await expect(page.getByRole("tab",{name:"Search sources",exact:true})).toHaveAttribute("data-state","active");
});
for (const code of ["knowledgeChanged","denied","notFound","identityChanged"])
  test(`${code} clears evidence and requires reinspection before another export`,async({page}) => {
    await enter(page);
    await control(page,"exportMode",code);
    await button(page).click();
    await expect(page.getByText(/Reopen it before exporting|no longer available for export/)).toBeVisible();
    await expect(article(page)).toHaveCount(0);
    await expect(button(page)).toHaveCount(0);
    await expect(page.getByRole("button",{name:code === "identityChanged" ? "Load saved proposals" : "Refresh saved proposals",exact:true})).toBeEnabled();
  });

test("lost connection during an owned export retains uncertainty and ignores late success",async({page}) => {
  await enter(page);
  await control(page,"delay");
  await button(page).click();
  await expect(page.getByRole("button",{name:"Cancel",exact:true})).toHaveCount(0);
  await journey(page,"setAvailable",false);
  await expect(page.getByText(/connection changed during export/)).toBeVisible();
  await expect(article(page)).toHaveCount(0);
  await control(page,"release");
  await journey(page,"setAvailable",true);
  await expect(page.getByText(/It may have saved a file/)).toBeVisible();
  await expect(page.getByText(/Review package saved\./)).toHaveCount(0);
  await expect(page.getByRole("button",{name:"Load saved proposals",exact:true})).toBeEnabled();
});

test("account changes clear private feedback and ignore the previous owner's late file path",async({page}) => {
  await enter(page);
  await control(page,"delay");
  await button(page).click();
  await journey(page,"recheckConnection","2");
  await control(page,"release");
  await expect(article(page)).toHaveCount(0);
  await expect(page.getByText(/Review package saved\.|It may have saved a file/)).toHaveCount(0);
  await page.locator("summary").filter({hasText:"Open a proposal reference"}).click();
  await expect(page.getByLabel("Connection proposal reference")).toHaveValue("");
  await expect(page.getByRole("button",{name:"Load saved proposals",exact:true})).toBeEnabled();
});

test("completion in another task does not move keyboard focus",async({page}) => {
  await enter(page);
  await control(page,"delay");
  await button(page).click();
  await page.getByRole("button",{name:"Search current sources",exact:true}).click();
  const query=page.getByLabel("What reviewed information are you looking for?");
  await query.focus();
  await control(page,"release");
  await expect(query).toBeFocused();
  await page.getByRole("tab",{name:"Review proposals",exact:true}).click();
  await expect(page.getByText(/Review package saved\./)).toBeVisible();
});

test("repeated keyboard activation while the picker is pending admits only one export",async({page}) => {
  await enter(page);
  await control(page,"delay");
  await button(page).focus();
  await page.keyboard.press("Enter");
  await expect(button(page)).toHaveAttribute("aria-disabled","true");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button",{name:"Cancel",exact:true})).toHaveCount(0);
  expect(await page.evaluate(() => (globalThis as any).__proposalInspection.calls.filter((call:any) => call.command === "export_connection_review_package").length)).toBe(1);
  await control(page,"release");
  await expect(button(page)).toHaveAttribute("aria-disabled","false");
  await expect(button(page)).toBeFocused();
});

test("a Curator handoff waits for the owned export instead of cancelling or replacing it",async({page}) => {
  await page.setViewportSize({width:360,height:900});
  const oldReference="f".repeat(64);
  await enter(page,oldReference);
  await control(page,"delay");
  await button(page).click();
  await page.getByRole("tab",{name:"Search sources",exact:true}).click();
  await page.getByLabel("What reviewed information are you looking for?").fill("launch approval");
  await page.getByRole("button",{name:"Search knowledge",exact:true}).click();
  await journey(page,"setStatus","librarian_query","complete");
  await page.getByLabel("Why are these connected?").fill("The launch review references the approval decision.");
  await page.getByRole("button",{name:"Review connection",exact:true}).click();
  await journey(page,"setStatus","curator_proposal","proposed");
  await page.getByRole("button",{name:"Inspect saved connection",exact:true}).click();
  const next=page.getByRole("button",{name:"Open new saved connection",exact:true});
  await expect(page.getByText(/Finish or cancel the file picker/)).toBeVisible();
  await expect(next).toBeDisabled();
  await control(page,"release");
  await expect(page.getByText(/Review package saved\./)).toBeVisible();
  await expect(next).toBeEnabled();
  await next.click();
  await expect(article(page)).toBeVisible();
  await expect(page.getByText(/Review package saved\./)).toHaveCount(0);
  const calls=await page.evaluate(() => (globalThis as any).__proposalInspection.calls);
  expect(calls.filter((call:any) => call.command === "export_connection_review_package").map((call:any) => call.args.proposalId)).toEqual([oldReference]);
  expect(calls.some((call:any) => call.command === "cancel_knowledge_connections")).toBe(false);
  expect(calls.filter((call:any) => call.args.request?.action === "proposal").map((call:any) => call.args.request.proposalId)).toEqual([oldReference,proposalReference]);
});
