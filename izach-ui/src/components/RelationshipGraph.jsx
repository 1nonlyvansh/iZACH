import React, { useEffect, useRef, useState } from 'react'
import * as d3 from 'd3'

const BASE = 'http://localhost:5050'

function SectionHeader({ label }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 16px 6px' }}>
      <span style={{ color: '#00e5ff' }}>*</span>
      <span style={{ color: '#00e5ff', fontFamily: "'Share Tech Mono'", fontSize: '10px', letterSpacing: '0.2em' }}>
        {label}
      </span>
      <div style={{ flex: 1, height: 1, background: '#0d2a3a' }} />
    </div>
  )
}

export default function RelationshipGraph() {
  const svgRef = useRef(null)
  const [people, setPeople] = useState([])
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(true)

  const loadPeople = () => {
    setLoading(true)
    fetch(`${BASE}/relationships`)
      .then(r => r.json())
      .then(d => {
        setPeople(d.people || [])
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }

  useEffect(() => { loadPeople() }, [])

  // D3 force graph
  useEffect(() => {
    if (!people.length || !svgRef.current) return

    const W = 220, H = 200
    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()
    svg.attr('width', W).attr('height', H)

    // Build nodes: center "YOU" + each person
    const nodes = [
      { id: '__you__', label: 'YOU', type: 'self' },
      ...people.map(p => ({ id: p.name, label: p.name, type: 'person', facts: p.facts })),
    ]

    // All edges connect to center
    const links = people.map(p => ({ source: '__you__', target: p.name }))

    const sim = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(links).id(d => d.id).distance(60).strength(0.7))
      .force('charge', d3.forceManyBody().strength(-120))
      .force('center', d3.forceCenter(W / 2, H / 2))
      .force('collision', d3.forceCollide(22))

    const g = svg.append('g')

    // Links
    const link = g.append('g')
      .selectAll('line')
      .data(links)
      .enter().append('line')
      .attr('stroke', '#1a4a5a')
      .attr('stroke-width', 1)
      .attr('stroke-opacity', 0.6)

    // Nodes
    const node = g.append('g')
      .selectAll('g')
      .data(nodes)
      .enter().append('g')
      .style('cursor', 'pointer')
      .on('click', (_, d) => {
        if (d.type !== 'self') setSelected(d)
      })

    node.append('circle')
      .attr('r', d => d.type === 'self' ? 12 : 8)
      .attr('fill', d => d.type === 'self' ? 'rgba(0,229,255,0.25)' : 'rgba(0,229,255,0.12)')
      .attr('stroke', d => d.type === 'self' ? '#00e5ff' : '#1a4a5a')
      .attr('stroke-width', d => d.type === 'self' ? 1.5 : 1)

    node.append('text')
      .attr('text-anchor', 'middle')
      .attr('dy', d => d.type === 'self' ? '0.35em' : '2.0em')
      .attr('fill', d => d.type === 'self' ? '#00e5ff' : '#3a6070')
      .attr('font-family', "'Share Tech Mono'")
      .attr('font-size', d => d.type === 'self' ? '7px' : '6.5px')
      .attr('letter-spacing', '0.05em')
      .text(d => d.label.length > 8 ? d.label.slice(0, 7) + '…' : d.label)

    // Drag
    const drag = d3.drag()
      .on('start', (event, d) => { if (!event.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y })
      .on('drag',  (event, d) => { d.fx = event.x; d.fy = event.y })
      .on('end',   (event, d) => { if (!event.active) sim.alphaTarget(0); d.fx = null; d.fy = null })
    node.call(drag)

    sim.on('tick', () => {
      link
        .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x).attr('y2', d => d.target.y)
      node.attr('transform', d => `translate(${Math.max(12, Math.min(W - 12, d.x))},${Math.max(12, Math.min(H - 12, d.y))})`)
    })

    return () => sim.stop()
  }, [people])

  return (
    <div style={{ borderTop: '1px solid #0d2a3a' }}>
      <div style={{ display: 'flex', alignItems: 'center' }}>
        <div style={{ flex: 1 }}>
          <SectionHeader label="RELATIONSHIP MAP" />
        </div>
        <button
          onClick={loadPeople}
          style={{
            background: 'transparent', border: 'none', color: '#1a4a5a',
            fontFamily: "'Share Tech Mono'", fontSize: '9px', cursor: 'pointer',
            padding: '0 10px', lineHeight: 1,
          }}
        >⟳</button>
      </div>

      {loading ? (
        <p style={{ color: '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: '9px', padding: '8px 16px' }}>
          LOADING...
        </p>
      ) : people.length === 0 ? (
        <p style={{ color: '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: '9px', padding: '8px 16px' }}>
          NO CONTACTS SAVED
        </p>
      ) : (
        <>
          <div style={{ display: 'flex', justifyContent: 'center', padding: '0 8px' }}>
            <svg ref={svgRef} style={{ overflow: 'visible' }} />
          </div>

          {/* Selected person detail card */}
          {selected && (
            <div style={{
              margin: '4px 12px 8px',
              padding: '8px 10px',
              background: 'rgba(0,229,255,0.04)',
              border: '1px solid #1a4a5a',
              borderRadius: 4,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                <span style={{ color: '#00e5ff', fontFamily: "'Share Tech Mono'", fontSize: '9px', letterSpacing: '0.1em' }}>
                  {selected.label.toUpperCase()}
                </span>
                <button
                  onClick={() => setSelected(null)}
                  style={{ background: 'none', border: 'none', color: '#1a4a5a', cursor: 'pointer', fontSize: '10px' }}
                >✕</button>
              </div>
              {selected.facts && Object.entries(selected.facts).map(([k, v]) => (
                <div key={k} style={{ display: 'flex', gap: 6, marginBottom: 2 }}>
                  <span style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '9px', minWidth: 55 }}>
                    {k.replace(/_/g, ' ')}
                  </span>
                  <span style={{ color: '#3a6070', fontFamily: "'JetBrains Mono'", fontSize: '9px' }}>
                    {String(v).slice(0, 28)}
                  </span>
                </div>
              ))}
            </div>
          )}

          <p style={{ color: '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: '8px', padding: '0 16px 8px', letterSpacing: '0.1em' }}>
            {people.length} CONTACT{people.length !== 1 ? 'S' : ''} · CLICK TO INSPECT
          </p>
        </>
      )}
    </div>
  )
}
