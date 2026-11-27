import { useId } from 'react'

const descriptions = {
  intersection: 'Somente a região comum a A e B está destacada.',
  union: 'Toda a área de A e B, incluindo a região comum, está destacada.',
  complement: 'A região de U fora de A está destacada.',
  symmetricDifference: 'As regiões exclusivas de A e B estão destacadas.',
  difference: 'A região de A fora de B está destacada.',
}

export type SetOperation = keyof typeof descriptions

const circleA = { cx: 44, cy: 33, r: 23 }
const circleB = { cx: 76, cy: 33, r: 23 }

export function VennDiagram({ operation }: { operation: SetOperation }) {
  const id = useId()
  const complement = operation === 'complement'

  return (
    <svg className="venn-diagram" viewBox="0 0 120 66" role="img" aria-label={descriptions[operation]}>
      {complement ? <>
        <path className="venn-fill" fillRule="evenodd"
          d="M10 6H110V60H10Z M60 14a19 19 0 1 0 0 38a19 19 0 1 0 0 -38Z" />
        <rect className="venn-outline" x="10" y="6" width="100" height="54" />
        <circle className="venn-outline" cx="60" cy="33" r="19" />
        <text x="23" y="36">U</text>
        <text x="60" y="36">A</text>
      </> : <>
        <defs>
          <clipPath id={`${id}-intersection`}><circle {...circleB} /></clipPath>
          <mask id={`${id}-outside-a`} x="0" y="0" width="120" height="66" maskUnits="userSpaceOnUse">
            <rect width="120" height="66" fill="white" />
            <circle {...circleA} fill="black" />
          </mask>
          <mask id={`${id}-outside-b`} x="0" y="0" width="120" height="66" maskUnits="userSpaceOnUse">
            <rect width="120" height="66" fill="white" />
            <circle {...circleB} fill="black" />
          </mask>
        </defs>
        {operation === 'intersection' && <circle className="venn-fill" {...circleA} clipPath={`url(#${id}-intersection)`} />}
        {operation === 'union' && <g className="venn-fill"><circle {...circleA} /><circle {...circleB} /></g>}
        {(operation === 'difference' || operation === 'symmetricDifference') &&
          <circle className="venn-fill" {...circleA} mask={`url(#${id}-outside-b)`} />}
        {operation === 'symmetricDifference' &&
          <circle className="venn-fill" {...circleB} mask={`url(#${id}-outside-a)`} />}
        <circle className="venn-outline" {...circleA} />
        <circle className="venn-outline" {...circleB} />
        <text x="37" y="36">A</text>
        <text x="83" y="36">B</text>
      </>}
    </svg>
  )
}
