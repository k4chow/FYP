import { getDisapproval } from '../lib/disapproval'

// A tiny, cosmetic "Cherie's Disapproval™" note shown under a film card. It is
// purely informational: the film still appears, still ranks, and can still be
// opened, saved, and watched. Renders nothing when the film isn't flagged.
export default function DisapprovalNote({
  title,
  year,
}: {
  title: string
  year: number | null
}) {
  const match = getDisapproval(title, year)
  if (!match) return null

  return (
    <div className="disapproval-note" role="note">
      <span className="disapproval-heading">
        <span aria-hidden="true">⚠️</span> Cherie's&nbsp;Disapproval™
      </span>
      <span className="disapproval-text">{match.warning}</span>
    </div>
  )
}