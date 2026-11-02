interface PlaceholderProps {
  title: string
  phase: number
}

export default function Placeholder({ title, phase }: PlaceholderProps) {
  return (
    <div>
      <h1 className="page-title">{title}</h1>
      <div className="card" style={{ marginTop: '1rem' }}>
        <p className="muted">This screen is built in Phase {phase}.</p>
      </div>
    </div>
  )
}
