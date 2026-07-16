<!--
  src/extensions/autoharn/components/ResourceFieldsCard.vue -- a labeled card + colored tier
  badge for a parsed `resource:` decision statement (design/USER-BLESSED-TABLE-TEMPLATE.md's
  six-field grammar: NAME, CLASS, REACH, WHAT-IT-PROVES, GUIDANCE, TIER), instead of the
  undifferentiated prose blob core/components/ItemDetail.vue renders the full statement as
  (cycle-4 audit finding 6, SERIOUS).

  Purely presentational: the parent (ItemObligationsPanel.vue) already fetched `GET /api/item/
  {row_id}/obligations` and only mounts this component when its `resource_fields` came back
  non-null (backend/extensions/autoharn/ledger_read.py's `parse_resource_fields`). Core's own
  item view keeps rendering the full raw statement UNCONDITIONALLY (core/components/
  ItemDetail.vue is untouched by this work) -- that IS the fallback for anything that doesn't
  parse cleanly, so this component only ever ADDS a structured view, never replaces or hides the
  original text.
-->
<script setup lang="ts">
import type { ResourceFields } from '../services/types'

defineProps<{ fields: ResourceFields }>()
</script>

<template>
  <section class="resource-card">
    <h3>
      Resource declaration
      <span class="badge" :class="`badge-tier-${fields.tier_kind}`">{{ fields.tier_kind }}</span>
    </h3>
    <dl class="resource-fields">
      <dt>name</dt>
      <dd>{{ fields.name }}</dd>
      <dt>class</dt>
      <dd>{{ fields.class_ }}</dd>
      <dt>reach</dt>
      <dd class="statement-text mono">{{ fields.reach }}</dd>
      <dt>what it proves</dt>
      <dd class="statement-text">{{ fields.what_it_proves }}</dd>
      <dt>guidance</dt>
      <dd class="statement-text">{{ fields.guidance }}</dd>
      <dt>tier</dt>
      <dd class="statement-text">{{ fields.tier }}</dd>
    </dl>
  </section>
</template>

<style scoped>
.resource-card h3 {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.resource-fields {
  display: grid;
  grid-template-columns: 8rem 1fr;
  gap: 0.35rem 0.75rem;
}
.resource-fields dt {
  font-weight: 600;
  color: var(--text-dim);
}
.resource-fields dd {
  margin: 0;
}
.statement-text {
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
/* Tier badge colors reuse the SAME semantic tokens the existing item-status badges do
   (style.css's badge-OPEN/WITNESSED/COSIGNED/AMBIGUOUS) rather than inventing new ones --
   forbidden gets the strongest (solid danger) treatment per design/ORCH-SPEC-RESOURCE-
   ACCOUNTING.md §3 ("a prohibition outranks a mandate for a reader's attention"); mandated is
   the warn treatment (a requirement, not merely a recommendation); blessed is the ok/green
   treatment (a positive recommendation); available is the neutral/open treatment (on record,
   no endorsement). Text label is always present alongside the color (SPEC.md sec 3
   accessibility floor: "color coding always paired with a shape/label channel"). */
.badge-tier-available { background: var(--open-bg); color: var(--open-text); }
.badge-tier-blessed { background: var(--ok-bg); color: var(--ok-text); }
.badge-tier-mandated { background: var(--warn-bg); color: var(--warn-text); border: 1px solid var(--warn-text); }
.badge-tier-forbidden { background: var(--danger); color: #fff; }
</style>
