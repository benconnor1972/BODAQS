<script lang="ts">
  interface Props {
    title: string;
  }
  const { title }: Props = $props();
</script>

<div class="empty-tile">
  <span class="title">{title}</span>
  <span class="msg">No data</span>
</div>

<style>
  .empty-tile {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 300px;
    background: #f5f5f5;
    border: 1px dashed #ccc;
    border-radius: 4px;
    color: #999;
    gap: 8px;
  }
  .title {
    font-size: 0.85rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .msg {
    font-size: 0.75rem;
  }
</style>
