/**
 * office/OfficeView.tsx
 *
 * The "Virtual Office View": a pixel-art room (Ninja Adventure assets, CC0)
 * where every pipeline node gets a desk with an agent that reacts to the
 * node's live execution status — idle at their desk, typing with a "…"
 * thought bubble while running, smiling when done, alarmed on error.
 *
 * Clicking a desk selects the node in the main app (RightPanel shows its
 * config). Hovering shows a tooltip with live token/cost stats.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Node as RFNode, Edge as RFEdge } from 'reactflow';
import type { PipelineNodeData } from '../canvas/nodes/PipelineNode';
import type { NodeStat } from '../panels/MonitorPanel';
import {
  FLOOR_TILE_POS,
  TILE,
  loadOfficeAssets,
  type OfficeImages,
} from './assets';
import { DESK_H, DESK_W, computeDeskLayout, fitScale, orderNodesForOffice, type OfficeLayout } from './layout';
import {
  OFFICE_FALLBACK_COLOR,
  OFFICE_TYPE_COLORS,
  PAL,
  STATUS_VISUALS,
  drawDesk,
  emoteBob,
  fallbackBubble,
  screenForStatus,
} from './sprites';

interface OfficeViewProps {
  nodes: RFNode<PipelineNodeData>[];
  edges: RFEdge[];
  nodeStats: Record<string, NodeStat>;
  animatedEdgeIds: Set<string>;
  isRunning: boolean;
  startTime: number | null;
  selectedNodeIds: string[];
  onSelectNode: (id: string) => void;
}

const LEGEND: ReadonlyArray<{ label: string; color: string }> = [
  { label: 'Idle', color: '#8b9bb4' },
  { label: 'Working…', color: '#2d697b' },
  { label: 'Done', color: '#56864c' },
  { label: 'Error', color: '#d14b34' },
];

/** Where a finished node's coin pile lands relative to its desk unit. */
const COIN_OFFSET = { x: 3, y: DESK_H - 14 };

export default function OfficeView({
  nodes,
  edges,
  nodeStats,
  animatedEdgeIds,
  isRunning,
  startTime,
  selectedNodeIds,
  onSelectNode,
}: OfficeViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [images, setImages] = useState<OfficeImages>({ chars: {}, emotes: {} });
  const [scale, setScale] = useState(1);
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  // Latest props for the animation loop without re-binding rAF each change.
  const propsRef = useRef({ nodes, edges, nodeStats, animatedEdgeIds });
  propsRef.current = { nodes, edges, nodeStats, animatedEdgeIds };

  // Desk layout depends only on how many nodes there are.
  const ordered = useMemo(() => orderNodesForOffice(nodes), [nodes]);
  const layout = useMemo(() => computeDeskLayout(ordered.length), [ordered.length]);

  useEffect(() => {
    let cancelled = false;
    loadOfficeAssets().then((imgs) => {
      if (!cancelled) setImages(imgs);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Fit the fixed-size room into the available area.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => {
      setScale(fitScale(el.clientWidth, el.clientHeight, layout.roomW, layout.roomH));
    };
    update();
    if (typeof ResizeObserver === 'undefined') return; // jsdom
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [layout.roomW, layout.roomH]);

  // Render loop. In jsdom getContext returns null and drawing is skipped.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || nodes.length === 0) return;
    let ctx: CanvasRenderingContext2D | null = null;
    try {
      ctx = canvas.getContext('2d');
    } catch {
      ctx = null;
    }
    if (!ctx) return;

    let raf = 0;
    const frame = (ms: number) => {
      const tick = Math.floor(ms / (1000 / 30));
      drawRoom(
        ctx!,
        tick,
        images,
        propsRef.current,
        layout,
        { hoveredId, selectedNodeIds },
      );
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [images, layout, hoveredId, isRunning, startTime, selectedNodeIds, nodes.length]);

  /** Convert a mouse event into room coordinates using the current scale. */
  const toRoomCoords = useCallback(
    (clientX: number, clientY: number): { x: number; y: number } | null => {
      const canvas = canvasRef.current;
      if (!canvas) return null;
      const rect = canvas.getBoundingClientRect();
      if (scale <= 0) return null;
      return { x: (clientX - rect.left) / scale, y: (clientY - rect.top) / scale };
    },
    [scale],
  );

  const hitTest = useCallback(
    (x: number, y: number): string | null => {
      for (let i = layout.slots.length - 1; i >= 0; i--) {
        const s = layout.slots[i];
        if (x >= s.x && x < s.x + DESK_W && y >= s.y && y < s.y + DESK_H) {
          return ordered[i]?.id ?? null;
        }
      }
      return null;
    },
    [layout, ordered],
  );

  const handleMove = (e: React.MouseEvent) => {
    const p = toRoomCoords(e.clientX, e.clientY);
    setHoveredId(p ? hitTest(p.x, p.y) : null);
  };

  const handleClick = (e: React.MouseEvent) => {
    const p = toRoomCoords(e.clientX, e.clientY);
    const id = p ? hitTest(p.x, p.y) : null;
    if (id) onSelectNode(id);
  };

  const hoveredIndex = hoveredId ? ordered.findIndex((n) => n.id === hoveredId) : -1;
  const hoveredSlot = hoveredIndex >= 0 ? layout.slots[hoveredIndex] : null;
  const hoveredNode = hoveredIndex >= 0 ? ordered[hoveredIndex] : null;
  const hoveredStat = hoveredId ? nodeStats[hoveredId] : undefined;

  return (
    <div
      ref={containerRef}
      data-testid="office-view"
      onMouseMove={handleMove}
      onClick={handleClick}
      style={{
        position: 'absolute',
        inset: 0,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: PAL.outline,
        overflow: 'hidden',
      }}
    >
      {nodes.length === 0 ? (
        <div
          data-testid="office-empty-hint"
          style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            color: '#aab6c4',
            fontFamily: 'var(--font-mono, monospace)',
            fontSize: 13,
          }}
        >
          No agents yet — build a pipeline and they will move in.
        </div>
      ) : (
        <div style={{ position: 'relative', width: layout.roomW * scale, height: layout.roomH * scale }}>
          <canvas
            ref={canvasRef}
            width={layout.roomW}
            height={layout.roomH}
            data-testid="office-canvas"
            style={{ width: '100%', height: '100%', imageRendering: 'pixelated', display: 'block' }}
          />
          {/* Name plates as DOM so text stays readable at any scale. */}
          {ordered.map((node, i) => (
            <NamePlate
              key={node.id}
              label={node.data.config?.custom_label || `${node.data.type}`}
              slot={layout.slots[i]}
              scale={scale}
              color={OFFICE_TYPE_COLORS[node.data.type ?? ''] ?? OFFICE_FALLBACK_COLOR}
              selected={selectedNodeIds.includes(node.id)}
            />
          ))}
          {hoveredNode && hoveredSlot && (
            <div
              data-testid="office-tooltip"
              style={{
                position: 'absolute',
                left: Math.min((hoveredSlot.x + DESK_W / 2) * scale, layout.roomW * scale - 90),
                top: (hoveredSlot.y + DESK_H) * scale + 14,
                transform: 'translateX(-50%)',
                pointerEvents: 'none',
                background: 'rgba(20,27,27,0.92)',
                border: `1px solid ${PAL.outline}`,
                borderRadius: 8,
                padding: '5px 10px',
                color: '#f2eaf1',
                fontSize: 11,
                fontFamily: 'var(--font-mono, monospace)',
                whiteSpace: 'nowrap',
                zIndex: 5,
              }}
            >
              <strong>{hoveredNode.data.config?.custom_label || hoveredNode.id}</strong>
              {' · '}
              {(hoveredNode.data.type || 'unknown').toUpperCase()}
              {' · '}
              {(hoveredNode.data.status || 'idle').toUpperCase()}
              {hoveredStat && (
                <>
                  {' · '}
                  {hoveredStat.tokensOut} out · ${hoveredStat.costUsd.toFixed(4)}
                </>
              )}
            </div>
          )}
        </div>
      )}
      <LegendPanel elapsedSec={isRunning && startTime ? (Date.now() - startTime) / 1000 : null} />
    </div>
  );
}

function NamePlate({
  label,
  slot,
  scale,
  color,
  selected,
}: {
  label: string;
  slot: { x: number; y: number };
  scale: number;
  color: string;
  selected: boolean;
}) {
  return (
    <div
      style={{
        position: 'absolute',
        left: (slot.x + DESK_W / 2) * scale,
        top: (slot.y + DESK_H + 1) * scale,
        transform: 'translateX(-50%)',
        display: 'flex',
        alignItems: 'center',
        gap: 4,
        padding: '1px 6px',
        borderRadius: 4,
        border: `1px solid ${selected ? '#c8d94a' : PAL.outline}`,
        background: 'rgba(43,54,67,0.85)',
        color: '#f2eaf1',
        fontSize: 9,
        fontFamily: 'var(--font-mono, monospace)',
        whiteSpace: 'nowrap',
        pointerEvents: 'none',
      }}
    >
      <span style={{ width: 6, height: 6, borderRadius: 99, background: color, flexShrink: 0 }} />
      {label}
    </div>
  );
}

function LegendPanel({ elapsedSec }: { elapsedSec: number | null }) {
  return (
    <div
      style={{
        position: 'absolute',
        left: 12,
        bottom: 12,
        display: 'flex',
        gap: 10,
        alignItems: 'center',
        padding: '5px 10px',
        borderRadius: 8,
        border: `1px solid ${PAL.outline}`,
        background: 'rgba(20,27,27,0.88)',
        color: '#aab6c4',
        fontSize: 10,
        fontFamily: 'var(--font-mono, monospace)',
        pointerEvents: 'none',
      }}
    >
      {LEGEND.map((l) => (
        <span key={l.label} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 7, height: 7, borderRadius: 2, background: l.color }} />
          {l.label}
        </span>
      ))}
      {elapsedSec !== null && (
        <span style={{ marginLeft: 6, color: PAL.screenGlow }}>⏱ {elapsedSec.toFixed(1)}s</span>
      )}
    </div>
  );
}

// ─── Room rendering ─────────────────────────────────────────────────────────

interface RoomViewState {
  nodes: RFNode<PipelineNodeData>[];
  edges: RFEdge[];
  nodeStats: Record<string, NodeStat>;
  animatedEdgeIds: Set<string>;
}

function drawRoom(
  ctx: CanvasRenderingContext2D,
  tick: number,
  imgs: OfficeImages,
  data: RoomViewState,
  layout: OfficeLayout,
  interaction: { hoveredId: string | null; selectedNodeIds: string[] },
): void {
  drawFloor(ctx, imgs, layout.roomW, layout.roomH);
  drawWallBand(ctx, layout.roomW);
  drawFlows(ctx, data, layout, tick);

  const ordered = orderNodesForOffice(data.nodes);
  for (let i = 0; i < layout.slots.length; i++) {
    const node = ordered[i];
    if (!node) continue;
    const slot = layout.slots[i];
    const status = node.data.status ?? 'idle';
    const agent = imgs.chars[node.data.type ?? ''];
    drawDesk(
      ctx,
      slot.x,
      slot.y,
      OFFICE_TYPE_COLORS[node.data.type ?? ''] ?? OFFICE_FALLBACK_COLOR,
      screenForStatus(status),
      tick + i * 7,
      interaction.hoveredId === node.id,
      agent,
    );
    const emoteKey = STATUS_VISUALS[status].emote;
    if (emoteKey) {
      const img = imgs.emotes[emoteKey];
      const ex = slot.x + 8;
      const ey = slot.y - 12 + emoteBob(tick);
      if (img) ctx.drawImage(img, ex, ey);
      else fallbackBubble(ctx, ex, ey, status);
    }
    if (status === 'done' && (data.nodeStats[node.id]?.costUsd ?? 0) > 0 && imgs.coin) {
      ctx.drawImage(imgs.coin, slot.x + COIN_OFFSET.x, slot.y + COIN_OFFSET.y);
    }
  }
}

/** Tile the whole room with the plain interior floor brick. */
function drawFloor(ctx: CanvasRenderingContext2D, imgs: OfficeImages, roomW: number, roomH: number): void {
  const floors = imgs.floors;
  if (!floors) {
    ctx.fillStyle = '#efd9ae';
    ctx.fillRect(0, 0, roomW, roomH);
    return;
  }
  const sx = FLOOR_TILE_POS.col * TILE;
  const sy = FLOOR_TILE_POS.row * TILE;
  for (let y = 0; y < roomH; y += TILE) {
    for (let x = 0; x < roomW; x += TILE) {
      ctx.drawImage(floors, sx, sy, TILE, TILE, x, y, TILE, TILE);
    }
  }
}

/** Solid wall band along the top edge of the room. */
function drawWallBand(ctx: CanvasRenderingContext2D, roomW: number): void {
  ctx.fillStyle = PAL.wallFace;
  ctx.fillRect(0, 0, roomW, 28);
  ctx.fillStyle = PAL.wallTop;
  ctx.fillRect(0, 0, roomW, 8);
  // Panel seams every 24px give the wall some rhythm.
  ctx.fillStyle = PAL.woodDark;
  for (let x = 12; x < roomW; x += 24) {
    ctx.fillRect(x, 8, 1, 16);
  }
  ctx.fillStyle = PAL.woodDark;
  ctx.fillRect(0, 24, roomW, 1);
  ctx.fillStyle = PAL.wallShadow;
  ctx.fillRect(0, 28, roomW, 3);
}

/** Dashed floor paths with a moving pulse for edges that are actively transferring data. */
function drawFlows(
  ctx: CanvasRenderingContext2D,
  data: RoomViewState,
  layout: OfficeLayout,
  tick: number,
): void {
  if (data.animatedEdgeIds.size === 0) return;
  const ordered = orderNodesForOffice(data.nodes);
  const slotById = new Map<string, { x: number; y: number }>();
  ordered.forEach((node, i) => {
    if (i < layout.slots.length) slotById.set(node.id, layout.slots[i]);
  });

  for (const edge of data.edges) {
    if (!data.animatedEdgeIds.has(edge.id ?? '')) continue;
    const a = slotById.get(edge.source);
    const b = slotById.get(edge.target);
    if (!a || !b) continue;
    const ax = a.x + DESK_W / 2;
    const ay = a.y + DESK_H - 8;
    const bx = b.x + DESK_W / 2;
    const by = b.y + DESK_H - 8;

    ctx.save();
    ctx.strokeStyle = PAL.screenOff;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(ax, ay);
    ctx.lineTo(bx, by);
    ctx.stroke();
    ctx.restore();

    // Pulse dot travelling source → target.
    const t = (tick % 40) / 40;
    const pxPos = Math.round(ax + (bx - ax) * t);
    const pyPos = Math.round(ay + (by - ay) * t);
    ctx.fillStyle = PAL.gold;
    ctx.fillRect(pxPos - 1, pyPos - 1, 3, 3);
    ctx.fillStyle = PAL.outline;
    ctx.fillRect(pxPos, pyPos, 1, 1);
  }
}
