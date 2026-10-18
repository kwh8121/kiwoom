import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";

test("sync → strategy → run → results → csv → rerun kept", async ({ page }) => {
  console.info("E2E phase: login");
  await page.goto("/login");
  await page.getByLabel("이메일").fill(process.env.E2E_EMAIL!);
  await page.getByLabel("비밀번호").fill(process.env.E2E_PASSWORD!);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL(/\/profiles$/);
  console.info("E2E phase: sync");
  const profile = page.locator("section").filter({ has: page.getByRole("heading", { name: process.env.E2E_ALIAS!, exact: true }) });
  await expect(profile.getByText("워커: 연결됨", { exact: true })).toBeVisible();
  await profile.getByRole("button", { name: "조건식 동기화", exact: true }).click();
  await expect(profile.getByText(/최근 동기화:.*succeeded/)).toBeVisible();
  await profile.getByRole("link", { name: "조건식 보기" }).click();
  await expect(page.getByRole("row")).toHaveCount(4);
  for (const name of ["기본종목", "전일고가돌파", "골든크로스"]) {
    await expect(page.getByRole("cell", { name, exact: true })).toBeVisible();
  }
  console.info("E2E phase: strategy");

  await page.goto("/strategies");
  await page.getByLabel("전략 이름").fill("E2E 조합 전략");
  await page.getByRole("button", { name: "전략 만들기", exact: true }).click();
  await expect(page).toHaveURL(/\/strategies\/[0-9a-f-]+$/);
  const strategyUrl = page.url();
  await page.getByRole("button", { name: "그룹으로 시작", exact: true }).click();
  const root = page.locator("fieldset").first();
  await root.getByRole("button", { name: "그룹 추가", exact: true }).click();
  await page.getByRole("combobox", { name: "조건식", exact: true }).nth(0).selectOption({ label: "기본종목" });
  // Remove the second default leaf so the root is AND(base, OR(...)).
  await root.locator(":scope > fieldset").nth(1).getByRole("button", { name: "삭제", exact: true }).click();
  await page.getByRole("combobox", { name: "조건식", exact: true }).nth(1).selectOption({ label: "전일고가돌파" });
  await page.getByRole("combobox", { name: "조건식", exact: true }).nth(2).selectOption({ label: "골든크로스" });
  const expression = "기본종목 AND (전일고가돌파 OR 골든크로스)";
  await expect(page.getByRole("region", { name: "미리보기" }).getByText(expression, { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "새 버전 저장", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("버전 1을 저장했습니다.");
  console.info("E2E phase: first search");
  await page.getByRole("button", { name: "검색 실행", exact: true }).click();
  await expect(page).toHaveURL(/\/runs\/[0-9a-f-]+$/);
  const firstRunUrl = page.url();
  await expect(page.getByRole("status")).toHaveText("성공 · 2건");
  const results = page.getByRole("table", { name: "조건 조합 결과" });
  await expect(results.getByRole("row")).toHaveCount(3);
  for (const code of ["005930", "0010F0"]) {
    await expect(results.getByRole("cell", { name: code, exact: true })).toBeVisible();
  }
  await expect(results.getByRole("cell", { name: "000660", exact: true })).toHaveCount(0);
  await expect(page.getByText("추출된 종목은 조건 조합의 결과일 뿐, 매수 추천이나 검증된 신호가 아닙니다.", { exact: true })).toBeVisible();
  console.info("E2E phase: CSV");
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: "CSV 다운로드" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^run-[0-9a-f-]+\.csv$/);
  const csv = await readFile((await download.path())!, "utf8");
  expect(csv.startsWith("\uFEFF종목코드,원본코드,종목명,유형,충족조건,변화,현재가,등락률\r\n")).toBe(true);
  expect(csv).toContain("0010F0,A0010F0,");
  expect(csv).toContain("005930,A005930,");
  expect(csv).not.toContain("000660");
  expect(csv.trimEnd().split("\r\n")).toHaveLength(3);
  console.info("E2E phase: rerun");

  await page.goto(strategyUrl);
  await page.getByRole("button", { name: "검색 실행", exact: true }).click();
  await expect(page).toHaveURL(/\/runs\/[0-9a-f-]+$/);
  expect(page.url()).not.toBe(firstRunUrl);
  await expect(page.getByRole("status")).toHaveText("성공 · 2건");
  for (const code of ["005930", "0010F0"]) {
    const row = page.getByRole("row").filter({ has: page.getByRole("cell", { name: code, exact: true }) });
    await expect(row.getByRole("cell", { name: "유지", exact: true })).toBeVisible();
  }
  await expect(page.getByRole("link", { name: "비교 대상 실행" })).toHaveAttribute("href", new URL(firstRunUrl).pathname);
});
