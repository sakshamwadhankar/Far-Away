import { test, expect } from '@playwright/test';

test.describe('Autosave & crash recovery', () => {
  test('a graph is restored across a full app restart and can be discarded', async ({ page }) => {
    await page.goto('/');

    // Dismiss the first-run guided tour if it appears.
    try {
      const skipTour = page.getByRole('button', { name: 'Skip' });
      await skipTour.waitFor({ state: 'visible', timeout: 5000 });
      await skipTour.click();
    } catch {
      // Tour already dismissed — nothing to do.
    }

    await page.waitForFunction(() => typeof (window as any).setE2EState === 'function');

    // Build a graph, then let the debounced autosave fire.
    await page.evaluate(() => {
      const nodes = [
        { id: 'n_in', type: 'pipelineNode', position: { x: 100, y: 100 }, data: { type: 'input', outputs: [{ name: 'prompt', type: 'text' }] } },
        { id: 'n_out', type: 'pipelineNode', position: { x: 400, y: 100 }, data: { type: 'output', inputs: [{ name: 'response', type: 'text' }] } },
      ];
      const edges = [
        { id: 'e1', source: 'n_in', target: 'n_out', sourceHandle: 'text:prompt', targetHandle: 'text:response' },
      ];
      (window as any).setE2EState(nodes, edges);
    });
    // Wait for the debounced write (estimate refreshes can re-arm it).
    await page.waitForFunction(
      () => !!localStorage.getItem('komvos_autosave_draft_v1'),
      null,
      { timeout: 10000 },
    );

    // Full renderer restart: reload the app from scratch.
    await page.reload();
    await page.waitForFunction(() => typeof (window as any).setE2EState === 'function');

    // The restored draft banner appears and both nodes are back on the canvas.
    await expect(page.getByTestId('draft-restored-banner')).toBeVisible();
    await expect(page.locator('.react-flow__node')).toHaveCount(2);

    // "Start clean" discards the draft and empties the canvas.
    await page.getByTestId('discard-draft').click();
    await expect(page.getByTestId('draft-restored-banner')).toBeHidden();
    await expect(page.locator('.react-flow__node')).toHaveCount(0);
    expect(
      await page.evaluate(() => !!localStorage.getItem('komvos_autosave_draft_v1')),
    ).toBe(false);
  });
});
