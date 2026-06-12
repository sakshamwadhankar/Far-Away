import { test, expect } from '@playwright/test';

test.describe('MERGE B Integration', () => {
  test('A pipeline built in the UI executes end-to-end with mock models and live updates', async ({ page }) => {
    // Navigate to the Vite dev server
    await page.goto('/');

    // Wait for the React app to mount and the setE2EState function to be available
    await page.waitForFunction(() => typeof (window as any).setE2EState === 'function');

    // Inject a 3-node pipeline programmatically to bypass brittle drag-and-drop
    await page.evaluate(() => {
      const nodes = [
        { 
          id: 'n_in', 
          type: 'pipelineNode', 
          position: { x: 100, y: 100 }, 
          data: { 
            type: 'input', 
            outputs: [{ name: 'prompt', type: 'text' }] 
          } 
        },
        { 
          id: 'n_model', 
          type: 'pipelineNode', 
          position: { x: 400, y: 100 }, 
          data: { 
            type: 'model', 
            endpoint_ref: 'mock:default', 
            inputs: [{ name: 'prompt', type: 'text' }], 
            outputs: [{ name: 'response', type: 'text' }], 
            config: { temperature: 0.7 } 
          } 
        },
        { 
          id: 'n_out', 
          type: 'pipelineNode', 
          position: { x: 700, y: 100 }, 
          data: { 
            type: 'output', 
            inputs: [{ name: 'response', type: 'text' }] 
          } 
        }
      ];

      const edges = [
        { 
          id: 'e1', 
          source: 'n_in', 
          target: 'n_model', 
          sourceHandle: 'text:prompt', 
          targetHandle: 'text:prompt' 
        },
        { 
          id: 'e2', 
          source: 'n_model', 
          target: 'n_out', 
          sourceHandle: 'text:response', 
          targetHandle: 'text:response' 
        }
      ];

      (window as any).setE2EState(nodes, edges);
    });

    // Verify nodes are injected correctly
    await expect(page.locator('.react-flow__node:has-text("INPUT")')).toBeVisible();
    await expect(page.locator('.react-flow__node:has-text("MODEL")')).toBeVisible();
    await expect(page.locator('.react-flow__node:has-text("OUTPUT")')).toBeVisible();

    // Click the Run Pipeline button
    const runBtn = page.getByTestId('run-pipeline-button');
    await expect(runBtn).toBeVisible();
    await runBtn.click();

    // The button should change to "Running..."
    await expect(runBtn).toHaveText('Running...');

    // Wait for the pipeline nodes to transition to "done"
    // Our UI modifies the node title to include "(done)"
    await expect(page.getByText('(done)', { exact: false }).first()).toBeVisible({ timeout: 10000 });
    
    // Check that button is back to "Run Pipeline"
    await expect(runBtn).toHaveText('Run Pipeline');
  });
});
