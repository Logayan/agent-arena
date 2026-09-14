import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { chromium } from 'playwright-core'

const frontendUrl = process.env.EVIDENCE_E2E_FRONTEND || 'http://127.0.0.1:5175'
const backendUrl = process.env.EVIDENCE_E2E_BACKEND || 'http://127.0.0.1:8005'
const runId = process.env.EVIDENCE_E2E_RUN || 'run_bda13e93b2ea'
const receiptOnlyArtifactId = process.env.EVIDENCE_E2E_RECEIPT_ONLY_ARTIFACT || 'artifact_6c329182d771'
const allowCompatibilityFallback = process.env.EVIDENCE_E2E_ALLOW_COMPAT === '1'
const outputRoot = path.resolve(process.env.EVIDENCE_E2E_OUTPUT || `../deliverables/${runId}/evidence-center-e2e/latest`)
const screenshotRoot = path.join(outputRoot, 'screenshots')
await mkdir(screenshotRoot, { recursive: true })

const cases = []
const results = []
const screenshots = []
const consoleErrors = []
const failedRequests = []
const httpErrors = []
const startedAt = new Date().toISOString()

function defineCase(id, title, expected) {
  cases.push({ id, title, expected, run_id: runId })
}

function record(id, status, actual, evidence = []) {
  results.push({ case_id: id, status, actual, evidence, finished_at: new Date().toISOString() })
}

async function shot(page, caseId, name, description) {
  const target = path.join(screenshotRoot, name)
  await page.screenshot({ path: target, fullPage: false, type: 'png' })
  const item = { case_id: caseId, path: `screenshots/${name}`, description }
  screenshots.push(item)
  return item.path
}

defineCase('EVC-001', '从真实 Run 打开应用内证据中心', '目标 Run 的测试证据入口可打开，截图筛选与数量可见')
defineCase('EVC-002', '应用内打开真实截图', '截图在灯箱中加载，支持上一张、下一张、缩放和原图下载')
defineCase('EVC-003', '查看 Artifact 来源与校验回执', '展示 Artifact ID、SHA-256、来源节点、Attempt 和三类验证回执')
defineCase('EVC-004', '筛选并查看非图片测试材料', '测试结果/JUnit/日志可筛选，正文或安全下载说明在应用内可见')
defineCase('EVC-005', '从正式交付卡片打开实际文件', '交付物展开后可直接进入应用内文件查看器，不再只显示元数据')
defineCase('EVC-006', '预览无扩展名与环境配置文本', 'Dockerfile、.env.example 等文本文件直接显示实际正文，不再只显示元数据')
defineCase('EVC-007', '缺失原字节时保持应用内闭环', '删除凭据明确标识原字节未归档，下载不会把页面带到 Not Found')

const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless: true,
  args: ['--disable-gpu', '--no-first-run', '--no-default-browser-check'],
})
const context = await browser.newContext({ viewport: { width: 1680, height: 1050 }, locale: 'zh-CN' })
const page = await context.newPage()
page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
page.on('requestfailed', request => {
  const error = request.failure()?.errorText || 'unknown'
  if (error !== 'net::ERR_ABORTED') failedRequests.push({ url: request.url(), error })
})
page.on('response', response => { if (response.status() >= 400) httpErrors.push({ url: response.url(), status: response.status() }) })

try {
  const [stateResponse, detailResponse, artifactsResponse, runsResponse] = await Promise.all([
    context.request.get(`${backendUrl}/api/platform/runs/${runId}/state?event_limit=100&organization_id=org_jianghu`, { timeout: 60000 }),
    context.request.get(`${backendUrl}/api/platform/runs/${runId}?event_limit=100&organization_id=org_jianghu`, { timeout: 60000 }),
    context.request.get(`${backendUrl}/api/platform/runs/${runId}/artifacts?organization_id=org_jianghu`, { timeout: 60000 }),
    context.request.get(`${backendUrl}/api/platform/runs?organization_id=org_jianghu`, { timeout: 60000 }),
  ])
  if (!stateResponse.ok()) throw new Error(`Run state HTTP ${stateResponse.status()}`)
  if (!detailResponse.ok()) throw new Error(`Run detail HTTP ${detailResponse.status()}`)
  if (!artifactsResponse.ok()) throw new Error(`Artifact listing HTTP ${artifactsResponse.status()}`)
  if (!runsResponse.ok()) throw new Error(`Run listing HTTP ${runsResponse.status()}`)
  const run = (await stateResponse.json()).run_state
  Object.assign(run, (await detailResponse.json()).run)
  run.artifacts = (await artifactsResponse.json()).artifacts
  const runSummary = (await runsResponse.json()).find(item => String(item.id) === runId)
  if (runSummary) Object.assign(run, runSummary)
  const imageArtifacts = [...(run.artifacts || [])].reverse().filter(item => String(item.media_type || '').startsWith('image/'))
  // A mature Run can contain full-page screenshots tens of thousands of
  // pixels tall. Loading one of those while the evidence list is also warming
  // thumbnail caches makes this smoke test depend on image-decoder throughput
  // instead of the product contract. Keep provenance coverage by preferring a
  // task-scoped image, but use a bounded real screenshot for the interaction.
  const imageArtifact = imageArtifacts.find(item => item.task_id && Number(item.size_bytes || 0) <= 2_000_000)
    || imageArtifacts.find(item => Number(item.size_bytes || 0) <= 2_000_000)
    || imageArtifacts.find(item => item.task_id)
    || imageArtifacts[0]
  if (!imageArtifact) throw new Error('真实 Run 中没有图片 Artifact')

  await page.goto(frontendUrl, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.getByRole('button', { name: '事件现场' }).click()
  const liveHeader = page.locator('.live-run-panel>header').filter({ hasText: `第 ${run.run_version} 版` })
  if (!await liveHeader.isVisible()) {
    const targetCard = page.locator('.run-list article').filter({ hasText: `当前第 ${run.run_version} 版` }).first()
    if (await targetCard.count()) {
      await targetCard.getByRole('button', { name: '查看现场' }).click()
    } else {
      const familyCard = page.locator('.run-list article').filter({ hasText: String(run.run_family_id || run.id) }).first()
      await familyCard.waitFor({ timeout: 240000 })
      await familyCard.getByRole('button', { name: '查看现场' }).click()
      const historicalVersion = page.locator('.run-version-history').getByRole('button', { name: new RegExp(`^第 ${run.run_version} 版`) })
      await historicalVersion.waitFor({ timeout: 240000 })
      await historicalVersion.click()
    }
  }
  await liveHeader.waitFor({ timeout: 240000 })
  await page.getByTestId('open-evidence-center').waitFor({ timeout: 240000 })
  await page.getByTestId('open-evidence-center').click()
  await page.getByTestId('evidence-center').waitFor({ timeout: 30000 })
  const centerShot = await shot(page, 'EVC-001', '01-evidence-center.png', '真实 Run 的应用内测试与证据中心')
  const centerText = await page.getByTestId('evidence-center').innerText()
  record('EVC-001', centerText.includes('测试与证据中心') && centerText.includes('截图') ? 'PASS' : 'FAIL', `run=${run.id}; version=${run.run_version}; screenshot_count=${run.test_evidence?.screenshots}`, [centerShot])

  const provenanceSearch = page.locator('.evidence-search input')
  await provenanceSearch.fill(String(imageArtifact.id))
  const imageItem = page.getByTestId(`evidence-item-${imageArtifact.id}`)
  await imageItem.waitFor({ timeout: 60000 })
  await imageItem.click()
  await page.getByTestId('evidence-lightbox').waitFor({ timeout: 60000 })
  const lightboxImage = page.getByTestId('evidence-lightbox').locator('img')
  await lightboxImage.waitFor({ state: 'attached', timeout: 60000 })
  await lightboxImage.evaluate((image, timeout) => new Promise((resolve, reject) => {
    const element = image
    if (element.complete && element.naturalWidth > 0) return resolve(true)
    const timer = setTimeout(() => reject(new Error('image decode timeout')), Number(timeout))
    element.addEventListener('load', () => { clearTimeout(timer); resolve(true) }, { once: true })
    element.addEventListener('error', () => { clearTimeout(timer); reject(new Error('image load failed')) }, { once: true })
  }), 120000)
  const imageLoaded = await lightboxImage.evaluate(image => {
    const bounds = image.getBoundingClientRect()
    return image.complete && image.naturalWidth > 0 && image.naturalHeight > 0 && bounds.width > 0 && bounds.height > 0
  })
  const lightboxShot = await shot(page, 'EVC-002', '02-image-lightbox.png', '真实证据截图在应用内大图浏览')
  await page.getByTestId('evidence-lightbox').getByRole('button', { name: '下一张' }).click()
  await page.getByTestId('evidence-lightbox').getByRole('button', { name: '关闭大图' }).click()
  record('EVC-002', imageLoaded ? 'PASS' : 'FAIL', `artifact=${imageArtifact.id}; size_bytes=${imageArtifact.size_bytes}; loaded=${imageLoaded}; navigation=next`, [lightboxShot])

  await provenanceSearch.fill(String(imageArtifact.id))
  await page.getByTestId(`evidence-item-${imageArtifact.id}`).click()
  await page.getByTestId('evidence-lightbox').waitFor({ timeout: 60000 })
  await page.getByTestId('evidence-lightbox').getByRole('button', { name: '关闭大图' }).click()
  const detail = page.getByTestId('evidence-detail-panel')
  const attemptPattern = new RegExp(`attempt:${runId}:`)
  if (allowCompatibilityFallback) {
    await detail.getByText(new RegExp(`来源回执接口尚未加载|attempt:${runId}:`)).waitFor({ timeout: 30000 })
  } else {
    await detail.getByText(attemptPattern).waitFor({ timeout: 30000 })
  }
  const detailText = await detail.innerText()
  const receiptCount = await detail.locator('.evidence-receipts li').count()
  const detailShot = await shot(page, 'EVC-003', '03-artifact-provenance.png', 'Artifact 元数据、来源 Attempt 与 Registry 回执')
  const fullProvenance = detailText.includes(`attempt:${runId}:`) && receiptCount >= 3
  const fallbackProvenance = allowCompatibilityFallback && detailText.includes('来源回执接口尚未加载')
  const provenancePassed = detailText.includes('Artifact ID') && detailText.includes('SHA-256') && detailText.includes('来源节点') && detailText.includes('来源 Attempt') && (fullProvenance || fallbackProvenance)
  record('EVC-003', provenancePassed ? 'PASS' : 'FAIL', `artifact=${imageArtifact.id}; receipts=${receiptCount}; compatibility_fallback=${fallbackProvenance}`, [detailShot])

  await provenanceSearch.fill('')
  await page.getByTestId('evidence-filter-test_results').click()
  const resultItems = page.locator('.evidence-artifact-list>button').filter({ hasNot: page.locator('.evidence-load-more') })
  const resultCount = await resultItems.count()
  if (resultCount > 0) await resultItems.first().click()
  await page.locator('.evidence-text-preview').waitFor({ timeout: 60000 })
  const resultShot = await shot(page, 'EVC-004', '04-test-result-filter.png', '测试结果证据筛选与应用内详情')
  const resultText = await page.getByTestId('evidence-center').innerText()
  const resultPassed = resultCount > 0 && resultText.includes('测试结果') && resultText.includes('下载原文件') && resultText.includes('应用内正文预览')
  record('EVC-004', resultPassed ? 'PASS' : 'FAIL', `filtered_result_count=${resultCount}`, [resultShot])

  await page.getByRole('button', { name: '关闭证据中心' }).click()
  const actualTextArtifact = [...(run.artifacts || [])].reverse().find(item => {
    if (!String(item.media_type || '').match(/text|json|xml|yaml/)) return false
    if (Number(item.size_bytes || 0) < 512) return false
    try { return JSON.parse(String(item.content || '{}')).change_action !== 'deleted' } catch { return true }
  })
  if (!actualTextArtifact) throw new Error('真实 Run 中没有可核对正文的交付文件')
  const deliveryCard = page.locator(`#artifact-${actualTextArtifact.id}`)
  await deliveryCard.waitFor({ timeout: 60000 })
  await deliveryCard.locator('summary').click()
  await deliveryCard.locator('[data-testid^="open-artifact-"]').click()
  await page.getByTestId('evidence-center').waitFor({ timeout: 30000 })
  await page.locator('.evidence-text-preview, .evidence-inline-image, .evidence-document-preview').first().waitFor({ state: 'visible', timeout: 60000 })
  const deliveryShot = await shot(page, 'EVC-005', '05-delivery-file-preview.png', '正式交付卡片直接打开应用内实际文件内容')
  const deliveryText = await page.getByTestId('evidence-center').innerText()
  const previewBody = await page.locator('.evidence-text-preview pre').innerText()
  const receiptOnly = /^\s*\{[\s\S]*"source_relative_path"[\s\S]*"sha256"[\s\S]*\}\s*$/.test(previewBody)
  record('EVC-005', deliveryText.includes('应用内正文预览') && !receiptOnly ? 'PASS' : 'FAIL', `delivery_card_to_in_app_preview=true; artifact=${actualTextArtifact.id}; receipt_only=${receiptOnly}`, [deliveryShot])

  const extensionlessArtifact = (run.artifacts || []).find(item => /(^|\/)(Dockerfile|\.env(?:\.[^/]+)*\.example)$/i.test(String(item.title || '').replaceAll('\\', '/')))
  if (!extensionlessArtifact) throw new Error('真实 Run 中没有 Dockerfile 或 .env.example Artifact')
  const evidenceSearch = page.locator('.evidence-search input')
  await evidenceSearch.fill(String(extensionlessArtifact.id))
  await page.getByTestId(`evidence-item-${extensionlessArtifact.id}`).click()
  await page.locator('.evidence-text-preview pre').waitFor({ state: 'visible', timeout: 60000 })
  const extensionlessBody = await page.locator('.evidence-text-preview pre').innerText()
  const extensionlessShot = await shot(page, 'EVC-006', '06-extensionless-text-preview.png', 'Dockerfile 或环境配置样例的实际正文预览')
  const extensionlessReceiptOnly = /^\s*\{[\s\S]*"source_relative_path"[\s\S]*"sha256"[\s\S]*\}\s*$/.test(extensionlessBody)
  record('EVC-006', extensionlessBody.trim().length > 0 && !extensionlessReceiptOnly ? 'PASS' : 'FAIL', `artifact=${extensionlessArtifact.id}; body_chars=${extensionlessBody.length}; receipt_only=${extensionlessReceiptOnly}`, [extensionlessShot])

  const receiptOnlyArtifact = (run.artifacts || []).find(item => String(item.id) === receiptOnlyArtifactId)
  if (!receiptOnlyArtifact) throw new Error('真实 Run 中没有用于缺失原字节提示验证的删除凭据')
  await evidenceSearch.fill(String(receiptOnlyArtifact.id))
  await page.getByTestId(`evidence-item-${receiptOnlyArtifact.id}`).click()
  await page.getByText('这是一条删除操作凭据，删除前原文件没有进入 Artifact Registry。').waitFor({ timeout: 60000 })
  const receiptShot = await shot(page, 'EVC-007', '07-receipt-only-friendly-state.png', '原字节缺失时的应用内友好说明与安全下载入口')
  const receiptDetailText = await page.getByTestId('evidence-detail-panel').innerText()
  record('EVC-007', receiptDetailText.includes('不会把它冒充为文件正文') && receiptDetailText.includes('下载删除凭据') ? 'PASS' : 'FAIL', `artifact=${receiptOnlyArtifact.id}; friendly_receipt_only=true`, [receiptShot])
} catch (error) {
  const pending = cases.filter(item => !results.some(result => result.case_id === item.id))
  for (const item of pending) record(item.id, 'FAIL', error instanceof Error ? error.stack || error.message : String(error))
  try { await shot(page, pending[0]?.id || 'EVC-FAIL', '99-failure.png', 'E2E 未捕获异常现场') } catch {}
} finally {
  await browser.close()
}

const finishedAt = new Date().toISOString()
const summary = {
  run_id: runId, frontend: frontendUrl, backend: backendUrl, started_at: startedAt, finished_at: finishedAt,
  passed: results.filter(item => item.status === 'PASS').length,
  failed: results.filter(item => item.status === 'FAIL').length,
  console_errors: consoleErrors,
  failed_requests: failedRequests,
  http_errors: httpErrors,
}
await writeFile(path.join(outputRoot, 'test-cases.json'), JSON.stringify({ run_id: runId, cases }, null, 2), 'utf8')
await writeFile(path.join(outputRoot, 'test-results.json'), JSON.stringify({ ...summary, results }, null, 2), 'utf8')
await writeFile(path.join(outputRoot, 'screenshot-index.json'), JSON.stringify({ run_id: runId, screenshots }, null, 2), 'utf8')
const junitCases = results.map(item => `<testcase classname="evidence-center" name="${item.case_id}">${item.status === 'FAIL' ? `<failure>${String(item.actual).replaceAll('&', '&amp;').replaceAll('<', '&lt;')}</failure>` : ''}</testcase>`).join('')
await writeFile(path.join(outputRoot, 'junit.xml'), `<?xml version="1.0" encoding="UTF-8"?><testsuite name="evidence-center" tests="${results.length}" failures="${summary.failed}">${junitCases}</testsuite>`, 'utf8')
const htmlRows = results.map(item => `<tr><td>${item.case_id}</td><td>${item.status}</td><td><pre>${String(item.actual).replaceAll('&', '&amp;').replaceAll('<', '&lt;')}</pre></td></tr>`).join('')
await writeFile(path.join(outputRoot, 'playwright-report.html'), `<!doctype html><meta charset="utf-8"><title>Evidence Center E2E</title><h1>Evidence Center E2E</h1><p>${runId}: ${summary.passed} passed / ${summary.failed} failed</p><table border="1"><tr><th>Case</th><th>Status</th><th>Actual</th></tr>${htmlRows}</table>`, 'utf8')
const files = ['test-cases.json', 'test-results.json', 'screenshot-index.json', 'junit.xml', 'playwright-report.html', ...screenshots.map(item => item.path)]
const manifest = []
for (const relative of files) {
  const bytes = await readFile(path.join(outputRoot, relative))
  manifest.push({ path: relative.replaceAll('\\', '/'), size_bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') })
}
await writeFile(path.join(outputRoot, 'sha256-manifest.json'), JSON.stringify({ run_id: runId, files: manifest }, null, 2), 'utf8')
console.log(JSON.stringify(summary, null, 2))
if (summary.failed || consoleErrors.length || failedRequests.length || httpErrors.length) process.exitCode = 1
