// @vitest-environment node
import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { fromPipelineSchema, toPipelineSchema } from './serializer';
import type { Pipeline } from '@shared/types';

// vitest runs with cwd = apps/desktop
const DIR = join(process.cwd(), '../../templates');

describe('bundled templates survive a canvas round-trip', () => {
  for (const file of readdirSync(DIR).filter(f => f.endsWith('.json'))) {
    it(file, () => {
      const original = JSON.parse(readFileSync(join(DIR, file), 'utf-8')) as Pipeline;
      const { nodes, edges } = fromPipelineSchema(original);
      const back = toPipelineSchema(nodes, edges);

      const ids = (p: Pipeline) => p.nodes.map(n => n.id).sort();
      expect(ids(back), 'nodes lost').toEqual(ids(original));

      const eset = (p: Pipeline) =>
        (p.edges as Array<{ from: string; to: string }>)
          .map(e => `${e.from}->${e.to}`).sort();
      expect(eset(back), 'edges lost').toEqual(eset(original));

      expect(Object.keys(back.endpoints ?? {}).sort(), 'endpoints lost')
        .toEqual(Object.keys(original.endpoints ?? {}).sort());

      for (const n of original.nodes.filter(n => n.type === 'access')) {
        const rt = back.nodes.find(x => x.id === n.id);
        expect(rt?.config?.access_policy, `policy lost on ${n.id}`)
          .toEqual(n.config?.access_policy);
      }
    });
  }
});
