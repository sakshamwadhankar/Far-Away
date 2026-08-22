/**
 * office/OfficeView.tsx
 *
 * The "Virtual Office View": an authentic, multi-room pixel-art office complex
 * (Ninja Adventure asset pack, CC0) where each pipeline node is an agent at
 * their workstation reacting live to execution state:
 *
 *  - Idle: agent sits quietly at desk, occasional subtle breath/blink, standby CRT dot
 *  - Running: agent types frantically with 4-frame action animation, screen scrolls code,
 *             "…" thought bubble floats above, data energy pulses along floor conduits
 *  - Done: agent celebrates with 4-frame victory jump, green ✓ screen, smiling emote 🙂,
 *          and spinning gold coin pile
 *  - Error: agent shakes in distress, flashing red ✗ screen, ❗ alert bubble, and
 *           rising animated smoke puffs
 *
 * Environment features full structural walls, windows with daylight, ticking clock,
 * server racks with blinking LEDs, animated swaying potted plants, water coolers,
 * bookshelves, and partition doorways.
 *
 * Hovering shows live execution metrics (tokens, time, cost). Clicking selects the node.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Node as RFNode, Edge as RFEdge } from 'reactflow';
import type { PipelineNodeData } from '../canvas/nodes/PipelineNode';
import type { NodeStat } from '../panels/MonitorPanel';
import {
  loadOfficeAssets,
  type OfficeImages,
} from './assets';
import {
  DESK_H,
  DESK_W,
  computeDeskLayout,
  fitScale,
  orderNodesForOffice,
  type OfficeLayout,
} from './layout';
import {
  OFFICE_FALLBACK_COLOR,
  OFFICE_TYPE_COLORS,
  PAL,
  STATUS_VISUALS,
  drawDesk,
  drawDoorways,
  drawFloorArea,
  drawOfficeFlows,
  drawOfficeProps,
  drawOfficeWalls,
  drawSmokePuff,
  drawSpinningCoin,
  emoteBob,
  fallbackBubble,
  getNodeThoughtText,
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
  { label: 'Working…', color: '#71ddee' },
  { label: 'Done', color: '#56864c' },
  { label: 'Error', color: '#d14b34' },
];

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

  // Synchronize latest props for the 30fps animation loop
  const propsRef = useRef({ nodes, edges, nodeStats, animatedEdgeIds });
  propsRef.current = { nodes, edges, nodeStats, animatedEdgeIds };

  // Compute room layout based on agent count
  const ordered = useMemo(() => orderNodesForOffice(nodes), [nodes]);
  const layout = useMemo(() => computeDeskLayout(ordered.length), [ordered.length]);

  // Load all pixel-art assets
  useEffect(() => {
    let cancelled = false;
    loadOfficeAssets().then((imgs) => {
      if (!cancelled) setImages(imgs);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Compute responsive fit scale
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => {
      setScale(fitScale(el.clientWidth, el.clientHeight, layout.roomW, layout.roomH));
    };
    update();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [layout.roomW, layout.roomH]);

  // Render loop
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
      drawOfficeComplex(
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

  /** Transform client mouse events to room pixel coordinates. */
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
        background: '#1a1824',
        overflow: 'hidden',
        userSelect: 'none',
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
            textAlign: 'center',
          }}
        >
          <div style={{ fontSize: 24, marginBottom: 8 }}>🏢</div>
          No agents yet — build a pipeline and they will move in.
        </div>
      ) : (
        <div
          style={{
            position: 'relative',
            width: layout.roomW * scale,
            height: layout.roomH * scale,
            boxShadow: '0 12px 36px rgba(0,0,0,0.6)',
            borderRadius: 6,
            overflow: 'hidden',
          }}
        >
          <canvas
            ref={canvasRef}
            width={layout.roomW}
            height={layout.roomH}
            data-testid="office-canvas"
            style={{
              width: '100%',
              height: '100%',
              imageRendering: 'pixelated',
              display: 'block',
            }}
          />

          {/* Department Room Title Headers */}
          {layout.rooms.map((room) => (
            <div
              key={room.id}
              style={{
                position: 'absolute',
                left: (room.x + 8) * scale,
                top: (room.y + 4) * scale,
                color: 'rgba(238, 207, 155, 0.75)',
                fontSize: Math.max(8, Math.round(9 * scale)),
                fontFamily: 'var(--font-mono, monospace)',
                fontWeight: 'bold',
                letterSpacing: 1,
                pointerEvents: 'none',
                textShadow: '0 1px 2px rgba(0,0,0,0.8)',
              }}
            >
              {room.name}
            </div>
          ))}

          {/* Character Live Thought / Speech Bubbles */}
          {ordered.map((node, i) => {
            const thought = getNodeThoughtText(node, nodeStats[node.id]);
            return (
              <ThoughtBubble
                key={`thought-${node.id}`}
                nodeId={node.id}
                thought={thought}
                slot={layout.slots[i]}
                scale={scale}
                status={node.data.status ?? nodeStats[node.id]?.status ?? 'idle'}
                selected={selectedNodeIds.includes(node.id)}
                isHovered={hoveredId === node.id}
              />
            );
          })}

          {/* Agent Name Plates */}
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

          {/* Live Hover Tooltip */}
          {hoveredNode && hoveredSlot && (
            <div
              data-testid="office-tooltip"
              style={{
                position: 'absolute',
                left: Math.min((hoveredSlot.x + DESK_W / 2) * scale, layout.roomW * scale - 120),
                top: (hoveredSlot.y + DESK_H) * scale + 12,
                transform: 'translateX(-50%)',
                pointerEvents: 'none',
                background: 'rgba(26, 24, 36, 0.95)',
                border: `1px solid ${PAL.gold}`,
                borderRadius: 6,
                padding: '6px 12px',
                color: '#f2eaf1',
                fontSize: 11,
                fontFamily: 'var(--font-mono, monospace)',
                whiteSpace: 'nowrap',
                boxShadow: '0 8px 24px rgba(0,0,0,0.7)',
                zIndex: 10,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                <span
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: 99,
                    background: OFFICE_TYPE_COLORS[hoveredNode.data.type ?? ''] ?? OFFICE_FALLBACK_COLOR,
                  }}
                />
                <strong>{hoveredNode.data.config?.custom_label || hoveredNode.id}</strong>
                <span style={{ color: PAL.screenGlow }}>({hoveredNode.data.type?.toUpperCase()})</span>
              </div>
              <div style={{ color: '#aab6c4', fontSize: 10 }}>
                Status:{' '}
                <span
                  style={{
                    color:
                      hoveredNode.data.status === 'running'
                        ? PAL.screenGlow
                        : hoveredNode.data.status === 'done'
                          ? PAL.ok
                          : hoveredNode.data.status === 'error'
                            ? PAL.error
                            : '#8b9bb4',
                  }}
                >
                  {(hoveredNode.data.status || 'idle').toUpperCase()}
                </span>
                {hoveredStat && (
                  <>
                    {' · '}
                    {hoveredStat.tokensOut} tokens · ${hoveredStat.costUsd.toFixed(4)}
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Bottom Status Legend */}
      <LegendPanel elapsedSec={isRunning && startTime ? (Date.now() - startTime) / 1000 : null} />
    </div>
  );
}

function ThoughtBubble({
  nodeId,
  thought,
  slot,
  scale,
  status,
  selected,
  isHovered,
}: {
  nodeId: string;
  thought: string;
  slot: { x: number; y: number };
  scale: number;
  status: string;
  selected: boolean;
  isHovered: boolean;
}) {
  const isRunning = status === 'running';
  const isDone = status === 'done';
  const isError = status === 'error';

  const borderColor = isRunning
    ? PAL.screenGlow
    : isDone
      ? PAL.ok
      : isError
        ? PAL.error
        : selected
          ? PAL.gold
          : PAL.woodLight;

  const textColor = isRunning
    ? '#71ddee'
    : isDone
      ? '#84c669'
      : isError
        ? '#ff706d'
        : selected
          ? '#f1c471'
          : '#f2eaf1';

  return (
    <div
      data-testid={`thought-bubble-${nodeId}`}
      style={{
        position: 'absolute',
        left: (slot.x + DESK_W / 2) * scale,
        top: (slot.y - 4) * scale,
        transform: 'translate(-50%, -100%)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        pointerEvents: 'none',
        zIndex: isHovered ? 25 : isRunning ? 20 : isDone ? 15 : 10,
        transition: 'all 0.1s steps(2)',
      }}
    >
      {/* Pixel-Art Box */}
      <div
        style={{
          background: isRunning ? '#0d1624' : isDone ? '#102214' : isError ? '#280f0f' : '#181522',
          border: `1px solid ${borderColor}`,
          outline: `1px solid ${PAL.outline}`,
          boxShadow: isRunning
            ? `0 0 0 1px ${PAL.outline}, 0 0 6px ${PAL.screenGlow}`
            : `0 0 0 1px ${PAL.outline}, 0 2px 0 0 rgba(0,0,0,0.8)`,
          padding: '1px 5px',
          color: textColor,
          fontSize: Math.max(8, Math.round(8 * scale)),
          fontFamily: '"Courier New", Courier, monospace',
          fontWeight: 700,
          letterSpacing: 0.5,
          whiteSpace: 'nowrap',
          maxWidth: Math.max(50, Math.round(66 * scale)),
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          imageRendering: 'pixelated',
          userSelect: 'none',
        }}
      >
        {thought}
      </div>

      {/* Stepped Pixel Pointer Tail */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', marginTop: 1 }}>
        <div
          style={{
            width: 6,
            height: 2,
            background: borderColor,
            borderLeft: `1px solid ${PAL.outline}`,
            borderRight: `1px solid ${PAL.outline}`,
          }}
        />
        <div
          style={{
            width: 3,
            height: 2,
            background: borderColor,
            borderLeft: `1px solid ${PAL.outline}`,
            borderRight: `1px solid ${PAL.outline}`,
            borderBottom: `1px solid ${PAL.outline}`,
          }}
        />
      </div>
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
        top: (slot.y + DESK_H + 2) * scale,
        transform: 'translateX(-50%)',
        display: 'flex',
        alignItems: 'center',
        gap: 4,
        padding: '1px 5px',
        border: `1px solid ${selected ? PAL.gold : PAL.outline}`,
        outline: selected ? `1px solid ${PAL.gold}` : 'none',
        background: '#161420',
        boxShadow: selected ? `0 0 6px ${PAL.gold}` : '0 2px 0 0 rgba(0,0,0,0.8)',
        color: '#f2eaf1',
        fontSize: Math.max(8, Math.round(8.5 * scale)),
        fontFamily: '"Courier New", Courier, monospace',
        fontWeight: 700,
        letterSpacing: 0.3,
        whiteSpace: 'nowrap',
        pointerEvents: 'none',
        imageRendering: 'pixelated',
      }}
    >
      <span style={{ width: 4, height: 4, background: color, flexShrink: 0, border: `1px solid ${PAL.outline}` }} />
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
        gap: 12,
        alignItems: 'center',
        padding: '6px 12px',
        borderRadius: 8,
        border: `1px solid ${PAL.outline}`,
        background: 'rgba(20, 24, 33, 0.90)',
        color: '#aab6c4',
        fontSize: 10,
        fontFamily: 'var(--font-mono, monospace)',
        pointerEvents: 'none',
      }}
    >
      {LEGEND.map((l) => (
        <span key={l.label} style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: l.color }} />
          {l.label}
        </span>
      ))}
      {elapsedSec !== null && (
        <span style={{ marginLeft: 8, color: PAL.screenGlow, fontWeight: 'bold' }}>
          ⏱ {elapsedSec.toFixed(1)}s
        </span>
      )}
    </div>
  );
}

// ─── Room Drawing Routine ──────────────────────────────────────────────────

interface RoomViewState {
  nodes: RFNode<PipelineNodeData>[];
  edges: RFEdge[];
  nodeStats: Record<string, NodeStat>;
  animatedEdgeIds: Set<string>;
}

function drawOfficeComplex(
  ctx: CanvasRenderingContext2D,
  tick: number,
  imgs: OfficeImages,
  data: RoomViewState,
  layout: OfficeLayout,
  interaction: { hoveredId: string | null; selectedNodeIds: string[] },
): void {
  // 1. Draw floor areas for each room
  if (layout.rooms.length > 0) {
    for (const room of layout.rooms) {
      drawFloorArea(ctx, imgs, room.x, room.y, room.w, room.h, room.floorStyle);
    }
  } else {
    drawFloorArea(ctx, imgs, 0, 0, layout.roomW, layout.roomH, 'woodWarm');
  }

  // 2. Draw architectural perimeter & partition walls
  drawOfficeWalls(ctx, imgs, layout.walls, layout.roomW, layout.roomH);
  drawDoorways(ctx, layout.doorways);

  // 3. Draw decorative props (animated plants, servers, water coolers, bookshelves)
  drawOfficeProps(ctx, imgs, layout.props, tick);

  // 4. Draw conduit wires and travelling flow pulses between connected desks
  const ordered = orderNodesForOffice(data.nodes);
  const slotMap = new Map<string, { x: number; y: number }>();
  ordered.forEach((node, i) => {
    if (i < layout.slots.length) {
      slotMap.set(node.id, layout.slots[i]);
    }
  });
  const dataFlowEdges = data.edges.map((e) => ({
    id: e.id ?? '',
    source: e.source,
    target: e.target,
  }));
  drawOfficeFlows(ctx, dataFlowEdges, data.animatedEdgeIds, slotMap, tick);

  // 5. Draw desks, animated agents, monitors, emotes, smoke, coins
  for (let i = 0; i < layout.slots.length; i++) {
    const node = ordered[i];
    if (!node) continue;
    const slot = layout.slots[i];
    const status = node.data.status ?? 'idle';
    const agentSheet = imgs.chars[node.data.type ?? ''];
    const isHovered = interaction.hoveredId === node.id;
    const isSelected = interaction.selectedNodeIds.includes(node.id);

    drawDesk(
      ctx,
      slot.x,
      slot.y,
      OFFICE_TYPE_COLORS[node.data.type ?? ''] ?? OFFICE_FALLBACK_COLOR,
      screenForStatus(status),
      status,
      tick + i * 5,
      isHovered,
      isSelected,
      agentSheet,
    );

    // Floating status emote bubble
    const emoteKey = STATUS_VISUALS[status].emote;
    if (emoteKey) {
      const img = imgs.emotes[emoteKey];
      const ex = slot.x + 8;
      const ey = slot.y - 14 + emoteBob(tick);
      if (img) {
        ctx.drawImage(img, ex, ey);
      } else {
        fallbackBubble(ctx, ex, ey, status);
      }
    }

    // Animated smoke puff on error
    if (status === 'error') {
      drawSmokePuff(ctx, imgs, slot.x + 30, slot.y + 10, tick);
    }

    // Spinning gold coin for finished nodes with cost
    if (status === 'done' && (data.nodeStats[node.id]?.costUsd ?? 0) > 0) {
      drawSpinningCoin(ctx, imgs, slot.x + 4, slot.y + DESK_H - 14, tick);
    }
  }
}
