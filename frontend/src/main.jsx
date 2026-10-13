import React, { useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Line, Bar } from 'react-chartjs-2';
import { Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, BarElement, Tooltip, Legend, Filler } from 'chart.js';
import { Activity, ArrowUpRight, CalendarDays, MapPin, ThermometerSun, Wind, Database, Download, Search, AlertTriangle } from 'lucide-react';
import './styles.css';
ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, BarElement, Tooltip, Legend, Filler);

const API = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8001').replace(/\/$/, '');
const fmt = n => n === null || n === undefined ? 'N/A' : Number(n).toLocaleString();
function App() {
  const [city,setCity]=useState('Pune');
  const [start,setStart]=useState('1990-01-01');
  const [end,setEnd]=useState('2020-12-31');
  const [data,setData]=useState(null);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState('');
  const [tab,setTab]=useState('frequency');

  async function analyze(e) {
    e?.preventDefault(); setLoading(true); setError(''); setData(null);
    try {
      const qs=new URLSearchParams({city:city.trim(),start,end});
      const r=await fetch(`${API}/api/analyze?${qs}`);
      const body=await r.json();
      if(!r.ok) throw new Error(body.detail || 'Analysis failed. Check the API server and try again.');
      setData(body);
    } catch(err) { setError(err.message || 'Could not connect to backend.'); }
    finally {setLoading(false);}
  }
  const labels=data?.yearly?.map(x=>x.year) || [];
  const yearly=data?.yearly || [];
  const chartOptions={responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false},tooltip:{backgroundColor:'#17242d',padding:12}}, scales:{x:{grid:{display:false},ticks:{color:'#87949d',maxTicksLimit:10}},y:{beginAtZero:true,grid:{color:'rgba(130,150,160,.13)'},ticks:{color:'#87949d'}}}};
  const lineData=useMemo(()=>({labels,datasets:[{label:tab==='frequency'?'Heatwave events':'Heatwave days',data:yearly.map(y=>tab==='frequency'?y.events:y.heatwave_days),borderColor:'#f59e65',backgroundColor:'rgba(245,158,101,.12)',fill:true,tension:.32,pointRadius:0,pointHoverRadius:5,borderWidth:2.5}]}),[data,tab]);
  const durationData=useMemo(()=>({labels,datasets:[{label:'Longest event (days)',data:yearly.map(y=>y.max_event_duration),backgroundColor:'#65b6ad',borderRadius:4,maxBarThickness:18}]}),[data]);
  function exportCsv(){
    if(!data)return;
    const rows=[['year','heatwave_events','heatwave_days','longest_event_days','mean_event_tmax_c'],...yearly.map(y=>[y.year,y.events,y.heatwave_days,y.max_event_duration,y.mean_event_tmax??''])];
    const csv=rows.map(row=>row.map(v=>`"${String(v).replaceAll('"','""')}"`).join(',')).join('\n');
    const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8;'}));a.download='heatwave-trend.csv';a.click();URL.revokeObjectURL(a.href);
  }
  const trend=data?.summary?.trend;
  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-icon"><Activity size={20}/></div><div><b>CLIMATIQ</b><small>CLIMATE INTELLIGENCE</small></div></div>
      <div className="side-label">WORKSPACE</div>
      <div className="nav-item active"><Activity size={17}/> Hazard analyzer</div>
      <div className="nav-item muted"><Wind size={17}/> Hazard library <span>SOON</span></div>
      <div className="nav-item muted"><Database size={17}/> Data sources</div>
      <div className="sidebar-bottom"><div className="live-dot"/> PUBLIC DATA MODE <small>Open-Meteo Archive API</small></div>
    </aside>
    <main className="main">
      <header className="topbar"><div className="breadcrumb">ANALYTICS <span>/</span> HAZARD TRENDS</div><div className="status"><span className="live-dot"/> SYSTEM OPERATIONAL</div></header>
      <section className="hero"><div className="eyebrow"><span/> CLIMATE RISK EXPLORER</div><h1>Understand the patterns.<br/><em>Anticipate the extremes.</em></h1><p>Explore historical climate hazards with long-range weather data. Start with heatwaves, identify trends, and turn observations into insight.</p></section>
      <form className="filters" onSubmit={analyze}>
        <div className="filter-field location-field"><label><MapPin size={13}/> LOCATION</label><input value={city} onChange={e=>setCity(e.target.value)} placeholder="Enter city" maxLength={100} required/><small>City or region name</small></div>
        <div className="filter-field"><label><ThermometerSun size={13}/> HAZARD TYPE</label><div className="select-look">Heatwave <span>DEFAULT</span></div><small>More hazards coming soon</small></div>
        <div className="filter-field"><label><CalendarDays size={13}/> FROM</label><input type="date" value={start} max={end} onChange={e=>setStart(e.target.value)} required/><small>Start date</small></div>
        <div className="filter-field"><label><CalendarDays size={13}/> TO</label><input type="date" value={end} min={start} onChange={e=>setEnd(e.target.value)} required/><small>End date</small></div>
        <button className="analyze-btn" disabled={loading}>{loading?'Analyzing…':<><Search size={16}/> Analyze trends</>}</button>
      </form>
      {error&&<div className="error"><AlertTriangle size={18}/><div><b>Analysis unavailable</b><p>{error}</p></div></div>}
      {!data&&!loading&&!error&&<section className="empty-state"><div className="empty-icon"><ThermometerSun size={26}/></div><h2>Your climate story starts here</h2><p>Choose a location and time range, then run the analysis to reveal heatwave frequency, duration, and long-term direction.</p><div className="empty-chips"><span>Historical data</span><span>Percentile-based detection</span><span>Trend analysis</span></div></section>}
      {loading&&<div className="loading"><div className="spinner"/><b>Processing historical observations…</b><span>Fetching daily temperatures and detecting heatwave events.</span></div>}
      {data&&<div className="results">
        <div className="result-heading"><div><div className="eyebrow"><span/> ANALYSIS COMPLETE</div><h2>{data.location}</h2><p>{data.period.start} — {data.period.end} · Daily maximum temperature</p></div><button className="export-btn" onClick={exportCsv}><Download size={15}/> Export CSV</button></div>
        <div className="metric-grid">
          <div className="metric"><div className="metric-label">TOTAL HEATWAVES <Activity size={16}/></div><strong>{fmt(data.summary.total_events)}</strong><small>Detected events in period</small></div>
          <div className="metric"><div className="metric-label">AVG. DURATION <CalendarDays size={16}/></div><strong>{data.summary.average_event_duration_days}<i> days</i></strong><small>Per detected event</small></div>
          <div className="metric"><div className="metric-label">95TH PERCENTILE <ThermometerSun size={16}/></div><strong>{data.methodology.threshold_celsius}<i>°C</i></strong><small>Selected-period threshold</small></div>
          <div className="metric"><div className="metric-label">TREND DIRECTION <ArrowUpRight size={16}/></div><strong className="trend-text">{trend?.direction || 'N/A'}</strong><small>{trend?.slope_events_per_year===null?'Insufficient data':`${trend.slope_events_per_year > 0?'+':''}${trend.slope_events_per_year} events / year`}</small></div>
        </div>
        <section className="panel"><div className="panel-head"><div><h3>Heatwave activity over time</h3><p>Annual counts derived from daily observations</p></div><div className="tabs"><button className={tab==='frequency'?'selected':''} onClick={()=>setTab('frequency')}>Frequency</button><button className={tab==='days'?'selected':''} onClick={()=>setTab('days')}>Heatwave days</button></div></div><div className="chart-wrap"><Line data={lineData} options={chartOptions}/></div></section>
        <div className="lower-grid"><section className="panel"><div className="panel-head"><div><h3>Event duration</h3><p>Longest detected event each year</p></div></div><div className="chart-wrap small"><Bar data={durationData} options={chartOptions}/></div></section>
        <section className="panel insight-panel"><div className="panel-head"><div><h3>Trend insights</h3><p>Statistical summary, not a forecast</p></div></div><div className="insight-stat"><span>Linear trend slope</span><b>{trend?.slope_events_per_year===null?'N/A':`${trend.slope_events_per_year > 0?'+':''}${trend.slope_events_per_year} <small>events/year</small>`}</b></div><div className="insight-stat"><span>Model R²</span><b>{trend?.r_squared ?? 'N/A'}</b></div><div className="insight-stat"><span>First → last year</span><b>{data.summary.first_year_events} → {data.summary.last_year_events}</b></div><p className="insight-note">{data.summary.first_to_last_year_change_percent===null?'Percentage change is undefined because the first year had zero events.':`First-to-last year event count changed by ${data.summary.first_to_last_year_change_percent}%. This compares two individual years and may be sensitive to natural variability.`}</p></section></div>
        <section className="panel table-panel"><div className="panel-head"><div><h3>Annual observations</h3><p>{yearly.length} calendar years · Missing temperature values excluded</p></div><span className="table-badge">RAW SUMMARY</span></div><div className="table-scroll"><table><thead><tr><th>YEAR</th><th>EVENTS</th><th>HEATWAVE DAYS</th><th>LONGEST EVENT</th><th>MEAN EVENT TMAX</th></tr></thead><tbody>{yearly.map(y=><tr key={y.year}><td>{y.year}</td><td>{y.events}</td><td>{y.heatwave_days}</td><td>{y.max_event_duration} days</td><td>{y.mean_event_tmax===null?'—':`${y.mean_event_tmax}°C`}</td></tr>)}</tbody></table></div></section>
        <div className="method-note"><AlertTriangle size={16}/><div><b>Interpret results carefully</b><p>Threshold: {data.methodology.threshold_celsius}°C. A heatwave is 3+ consecutive days strictly above the 95th percentile calculated from this selected period. {data.methodology.missing_days} missing daily values were excluded. {data.methodology.caveat}</p><small>Source: {data.source} · Cache: {data.cache} · Trend fit R²: {trend?.r_squared ?? 'N/A'}</small></div></div>
      </div>}
      <footer><span>CLIMATIQ © 2026</span><span>Built with public climate data <span className="live-dot"/></span></footer>
    </main>
  </div>
}
createRoot(document.getElementById('root')).render(<App/>);
