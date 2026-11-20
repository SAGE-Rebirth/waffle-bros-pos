// The dashboard grid. Normally it just lays the cards out; in "Customise" mode each card gets a
// toolbar: a drag handle (mouse, touch or keyboard), move earlier/later, narrower/wider and hide.
// Only the handle starts a drag, so scrolling and tapping charts never move a card by accident.
import { useState } from 'react';
import {
  DndContext, DragOverlay, KeyboardSensor, PointerSensor, closestCenter, pointerWithin, useSensor, useSensors,
} from '@dnd-kit/core';
import { SortableContext, sortableKeyboardCoordinates, useSortable } from '@dnd-kit/sortable';
import { WIDTHS, cardTitle, dropCard, moveCard, resizeCard, setHidden, widthLabel } from '../layout.js';

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

function SortableCard({ id, width, editing, first, last, layout, onChange, children }) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, isDragging, isOver, active, activeIndex, index } = useSortable({ id, disabled: !editing });
  // Dropping on a card puts the dragged card in its place: before it when moving back, after it when moving forward.
  const drop = isOver && active && active.id !== id ? (activeIndex > index ? ' drop-before' : ' drop-after') : '';
  const title = cardTitle(id);
  const pos = layout.order.indexOf(id);
  return (
    <div ref={setNodeRef} data-card={id}
      className={`dash-item span-${width}${editing ? ' editing' : ''}${isDragging ? ' dragging' : ''}${drop}`}>
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
            <span className="w num">{widthLabel(width)}</span>
            <button type="button" className="btn sm" disabled={width === WIDTHS.at(-1)} onClick={() => onChange(resizeCard(layout, id, +1))} aria-label={`Make ${title} wider`} title="Wider">+</button>
          </div>
          <button type="button" className="btn ghost sm" onClick={() => onChange(setHidden(layout, id, true))} aria-label={`Hide ${title}`}>Hide</button>
        </div>
      )}
      {children}
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
