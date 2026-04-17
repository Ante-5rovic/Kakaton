import { Routes, Route, Link } from 'react-router-dom'

function Home() {
  return <h1>Početna</h1>
}

function About() {
  return <h1>O nama</h1>
}

export default function App() {
  return (
    <div>
      <nav>
        <Link to="/">Početna</Link> | <Link to="/about">O nama</Link>
      </nav>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/about" element={<About />} />
      </Routes>
    </div>
  )
}