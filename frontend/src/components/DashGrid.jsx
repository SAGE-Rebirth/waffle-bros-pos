// The dashboard grid. Normally it just lays the cards out; in "Customise" mode each card gets a
// toolbar: a drag handle (mouse, touch or keyboard), move earlier/later, narrower/wider and hide.
// Only the handle starts a drag, so scrolling and tapping charts never move a card by accident.
// The right edge, bottom edge and bottom-right corner can be dragged to resize a card: the width
// snaps to the 12-column grid, the height to 10 px steps (double-click the bottom edge for auto).
import { useRef, useState } from 'react';
import {
  DndContext, DragOverlay, KeyboardSensor, PointerSensor, closestCenter, pointerWithin, useSensor, useSensors,
} from '@dnd-kit/core';
import { SortableContext, sortableKeyboardCoordinates, useSortable } from '@dnd-kit/sortable';
import {
  WIDTHS, cardTitle, dropCard, heightLabel, moveCard, resizeCard, setHidden, setSize, snapHeight, snapWidth, widthLabel,
} from '../layout.js';

// Every card is full width below this, as in styles.css, so only heights can be changed there.
const NARROW = '(max-width: 1100px)';
const isNarrow = () => typeof window !== 'undefined' && window.matchMedia?.(NARROW).matches;

// Drop where the finger or pointer is; fall back to the nearest card when it is in a gap.
const collision = (args) => {
  const hit = pointerWithin(args);
  return hit.length ? hit : closestCenter(args);
};

// Cards do not slide around while you drag (they have very different sizes, so sliding makes
// them overlap). Instead the card under the pointer shows a bar where the dragged card will land.
const noShift = () => null;

const announcements = {
  onDragStart: ({ active }) => `Picked up ${cardTitle(active.id)}.`,
  onDragOver: ({ active, over }) => (over ? `${cardTitle(active.id)} is over ${cardTitle(over.id)}.` : `${cardTitle(active.id)} is not over a card.`),
  onDragEnd: ({ active, over }) => (over ? `${cardTitle(active.id)} dropped in place of ${cardTitle(over.id)}.` : `${cardTitle(active.id)} dropped.`),
  onDragCancel: ({ active }) => `Moving ${cardTitle(active.id)} was cancelled.`,
};
const screenReaderInstructions = {
  draggable: 'To move this card, press space or enter, use the arrow keys, then press space or enter again to drop it, or escape to cancel.',
};

/** Drag to resize. Returns pointer-down handlers for each edge and the live size while dragging. */
function useResize({ id, layout, onChange, elRef }) {
  const [live, setLive] = useState(null); // {width, height} while a resize is in progress
  const start = (dir) => (e) => {
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    const el = elRef.current;
    const card = el?.querySelector(':scope > .card');
    if (!el || !card) return;
    e.preventDefault();
    e.stopPropagation();
    const grid = el.parentElement;
    const gap = parseFloat(getComputedStyle(grid).columnGap) || 16;
    const step = (grid.clientWidth - 11 * gap) / 12 + gap; // one grid column plus its gap
    const from = { x: e.clientX, y: e.clientY, cols: layout.width[id], h: card.getBoundingClientRect().height };
    const wide = !isNarrow();
    let size = { width: layout.width[id], height: layout.height?.[id] ?? null };
    const handle = e.currentTarget;
    handle.setPointerCapture?.(e.pointerId);
    const move = (ev) => {
      size = {
        width: dir.includes('e') && wide ? snapWidth(from.cols + (ev.clientX - from.x) / step) : size.width,
        height: dir.includes('s') ? snapHeight(from.h + (ev.clientY - from.y)) : size.height,
      };
      setLive(size);
    };
    const end = (ev) => {
      handle.removeEventListener('pointermove', move);
      handle.removeEventListener('pointerup', end);
      handle.removeEventListener('pointercancel', end);
      setLive(null);
      if (ev.type === 'pointerup') onChange(setSize(layout, id, size));
    };
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', end);
    handle.addEventListener('pointercancel', end);
    setLive(size);
  };
  // Arrow keys on a focused edge: 1 column sideways, 20 px up or down.
  const key = (dir) => (e) => {
    const h = layout.height?.[id] ?? elRef.current?.querySelector(':scope > .card')?.getBoundingClientRect().height ?? 300;
    const moves = {
      e: { ArrowLeft: { width: layout.width[id] - 1 }, ArrowRight: { width: layout.width[id] + 1 } },
      s: { ArrowUp: { height: h - 20 }, ArrowDown: { height: h + 20 }, Delete: { height: null }, Backspace: { height: null } },
    }[dir];
    const change = moves?.[e.key];
    if (!change) return;
    e.preventDefault();
    onChange(setSize(layout, id, change));
  };
  return { live, start, key };
}

function SortableCard({ id, width, editing, first, last, layout, onChange, children }) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, isDragging, isOver, active, activeIndex, index } = useSortable({ id, disabled: !editing });
  const elRef = useRef(null);
  const setRefs = (el) => { elRef.current = el; setNodeRef(el); };
  const { live, start, key } = useResize({ id, layout, onChange, elRef });
  const shownWidth = live?.width ?? width;
  const height = live ? live.height : layout.height?.[id] ?? null;
  // Dropping on a card puts the dragged card in its place: before it when moving back, after it when moving forward.
  const drop = isOver && active && active.id !== id ? (activeIndex > index ? ' drop-before' : ' drop-after') : '';
  const title = cardTitle(id);
  const pos = layout.order.indexOf(id);
  return (
    <div ref={setRefs} data-card={id} style={height ? { '--card-h': `${height}px` } : undefined}
      className={`dash-item span-${shownWidth}${height ? ' fixed-h' : ''}${editing ? ' editing' : ''}${isDragging ? ' dragging' : ''}${live ? ' resizing' : ''}${drop}`}>
      {editing && (
        <div className="dash-tools">
          <button type="button" ref={setActivatorNodeRef} className="drag-handle" {...attributes} {...listeners}
            aria-label={`Drag to move ${title}`} title="Drag to move">
            <span className="grip" aria-hidden="true">⠿</span><span className="t">{title}</span>
          </button>
          <div className="tool-group">
            <button type="button" className="btn sm" disabled={first} onClick={() => onChange(moveCard(layout, id, pos - 1))} aria-label={`Move ${title} earlier`} title="Move earlier">◀</button>
            <button type="button" className="btn sm" disabled={last} onClick={() => onChange(moveCard(layout, id, pos + 1))} aria-label={`Move ${title} later`} title="Move later">▶</button>
          </div>
          <div className="tool-group width">
            <button type="button" className="btn sm" disabled={width === WIDTHS[0]} onClick={() => onChange(resizeCard(layout, id, -1))} aria-label={`Make ${title} narrower`} title="Narrower">−</button>
            <span className="w num">{widthLabel(shownWidth)}</span>
            <button type="button" className="btn sm" disabled={width === WIDTHS.at(-1)} onClick={() => onChange(resizeCard(layout, id, +1))} aria-label={`Make ${title} wider`} title="Wider">+</button>
          </div>
          {layout.height?.[id] != null && (
            <button type="button" className="btn ghost sm" onClick={() => onChange(setSize(layout, id, { height: null }))} aria-label={`Automatic height for ${title}`} title="Fit the height to the content">↕ Auto</button>
          )}
          <button type="button" className="btn ghost sm" onClick={() => onChange(setHidden(layout, id, true))} aria-label={`Hide ${title}`}>Hide</button>
        </div>
      )}
      {children}
      {editing && <>
        <div className="rs rs-e" role="slider" tabIndex={0} aria-label={`Width of ${title}`} aria-valuemin={WIDTHS[0]} aria-valuemax={12} aria-valuenow={shownWidth}
          aria-valuetext={widthLabel(shownWidth)} title="Drag to change the width" onPointerDown={start('e')} onKeyDown={key('e')} />
        <div className="rs rs-s" role="slider" tabIndex={0} aria-label={`Height of ${title}`} aria-valuetext={heightLabel(height)}
          title="Drag to change the height · double-click for automatic height" onPointerDown={start('s')} onKeyDown={key('s')}
          onDoubleClick={() => onChange(setSize(layout, id, { height: null }))} />
        <div className="rs rs-se" aria-hidden="true" title="Drag to resize" onPointerDown={start('es')}
          onDoubleClick={() => onChange(setSize(layout, id, { height: null }))} />
        {live && <div className="size-badge num" aria-hidden="true">{widthLabel(shownWidth)} · {height ? `${height}px` : 'auto'}</div>}
      </>}
    </div>
  );
}

/**
 * @param layout   the saved layout (see layout.js)
 * @param cards    { [cardId]: element } for every card that can be shown
 * @param editing  whether Customise mode is on
 * @param onChange called with the new layout
 */
export default function DashGrid({ layout, cards, editing, onChange }) {
  const [active, setActive] = useState(null);
  const sensors = useSensors(
    // A few pixels of movement before a drag starts, so a tap on the handle stays a tap.
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const visible = layout.order.filter((id) => !layout.hidden.includes(id) && cards[id]);
  return (
    <DndContext sensors={sensors} collisionDetection={collision} accessibility={{ announcements, screenReaderInstructions }}
      onDragStart={(e) => setActive(e.active.id)}
      onDragEnd={(e) => { setActive(null); if (e.over) onChange(dropCard(layout, e.active.id, e.over.id)); }}
      onDragCancel={() => setActive(null)}>
      <SortableContext items={visible} strategy={noShift}>
        <div className={`dash${editing ? ' editing' : ''}`}>
          {visible.map((id, i) => (
            <SortableCard key={id} id={id} width={layout.width[id]} editing={editing} first={i === 0} last={i === visible.length - 1}
              layout={layout} onChange={onChange}>
              {cards[id]}
            </SortableCard>
          ))}
        </div>
      </SortableContext>
      <DragOverlay dropAnimation={null}>
        {active ? <div className="drag-chip"><span aria-hidden="true">⠿</span> {cardTitle(active)}</div> : null}
      </DragOverlay>
    </DndContext>
  );
}
