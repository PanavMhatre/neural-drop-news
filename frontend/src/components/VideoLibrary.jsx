import React, { useState, useEffect } from 'react';
import { Play, CheckCircle, AlertCircle, Clock, Calendar, Edit2, Loader2, Save, Trash2 } from 'lucide-react';
import { format } from 'date-fns';

export default function VideoLibrary() {
  const [videos, setVideos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedVideo, setSelectedVideo] = useState(null);
  const [scheduleTime, setScheduleTime] = useState('');
  const [videoSessionId, setVideoSessionId] = useState(Date.now());
  
  const [isEditing, setIsEditing] = useState(false);
  const [editScript, setEditScript] = useState('');
  const [editVoice, setEditVoice] = useState('en-US-JennyNeural');
  const [editColor, setEditColor] = useState('#ffffff');
  const [editVideoUrl, setEditVideoUrl] = useState('');
  const [isRerendering, setIsRerendering] = useState(false);
  const [deletingId, setDeletingId] = useState(null);
  const [activeProgress, setActiveProgress] = useState({});
  const previousProgressRef = React.useRef({});
  const apiOrigins = React.useMemo(() => {
    const origins = [];
    const configuredOrigin = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '');
    if (configuredOrigin) {
      origins.push(configuredOrigin);
    }
    if (window.location.port === '880') {
      origins.push(window.location.origin);
    }
    origins.push('http://localhost:880');
    return [...new Set(origins)];
  }, []);

  const apiFetch = async (path, options = {}) => {
    let lastError;
    for (const origin of apiOrigins) {
      try {
        const res = await fetch(`${origin}${path}`, options);
        if (res.status !== 404 || origin === apiOrigins[apiOrigins.length - 1]) {
          return res;
        }
        lastError = new Error(`Not found at ${origin}${path}`);
      } catch (err) {
        lastError = err;
      }
    }
    throw lastError || new Error('API request failed');
  };

  const mediaUrl = (id, filename) => {
    const origin = apiOrigins[0] || 'http://localhost:880';
    return `${origin}/media/${encodeURIComponent(id)}/${encodeURIComponent(filename)}?t=${videoSessionId}`;
  };

  useEffect(() => {
    fetchVideos();
    
    // Polling for progress
    const interval = setInterval(async () => {
      try {
        const res = await apiFetch('/api/progress');
        const data = await res.json();
        setActiveProgress(data);
        
        // Check for completions
        const prev = previousProgressRef.current;
        let finishedAny = false;
        for (const id in prev) {
          if (!(id in data)) {
            finishedAny = true;
          }
        }
        if (finishedAny) {
          fetchVideos();
        }
        previousProgressRef.current = data;
      } catch (e) {
        // Ignore network errors
      }
    }, 1000);
    
    return () => clearInterval(interval);
  }, []);

  const fetchVideos = async () => {
    try {
      const res = await apiFetch('/api/videos');
      const data = await res.json();
      setVideos(data.videos);
    } catch (err) {
      console.error("Failed to fetch videos", err);
    } finally {
      setLoading(false);
    }
  };

  const loadVideoDetails = async (id) => {
    try {
      const res = await apiFetch(`/api/videos/${encodeURIComponent(id)}`);
      const data = await res.json();
      setSelectedVideo(data);
      setVideoSessionId(Date.now());
      setIsEditing(false);
    } catch (err) {
      console.error("Failed to fetch details", err);
    }
  };

  const handleSchedule = async () => {
    if (!scheduleTime) return;
    try {
      const res = await apiFetch(`/api/schedule/${encodeURIComponent(selectedVideo.id)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scheduled_time: scheduleTime })
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Scheduling failed');
      }
      const channels = data.buffer_channels?.join(', ') || data.buffer_channel || 'NeuralDropBits';
      alert(`Scheduled in Buffer for ${channels}.`);
      setSelectedVideo(null);
      setScheduleTime('');
    } catch (err) {
      console.error("Failed to schedule", err);
      alert(err.message || 'Failed to schedule in Buffer');
    }
  };

  const handleEditClick = () => {
    setEditScript(selectedVideo.script.full_script);
    setEditColor('#ffffff'); // default or parse from somewhere
    setEditVoice('en-US-JennyNeural');
    setEditVideoUrl('');
    setIsEditing(true);
  };

  const handleReRender = async () => {
    setIsRerendering(true);
    try {
      await apiFetch(`/api/videos/${encodeURIComponent(selectedVideo.id)}/render`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          script_text: editScript,
          custom_video_url: editVideoUrl || null,
          accent_color_hex: editColor,
          tts_voice: editVoice
        })
      });
      alert('Re-render started! Check back in a few minutes.');
      setIsEditing(false);
      setSelectedVideo(null);
    } catch (err) {
      console.error(err);
      alert('Failed to start re-render');
    } finally {
      setIsRerendering(false);
    }
  };

  const handleDelete = async (video, event) => {
    event?.stopPropagation();
    const title = video.metadata?.title_options?.[0] || video.title || video.id;
    const confirmed = window.confirm(`Delete "${title}"? This removes the local package and media files.`);
    if (!confirmed) return;

    setDeletingId(video.id);
    try {
      const res = await apiFetch(`/api/videos/${encodeURIComponent(video.id)}`, {
        method: 'DELETE'
      });

      if (!res.ok) {
        let message = 'Delete failed';
        try {
          const data = await res.json();
          message = data.detail || message;
        } catch {
          message = `${message} (${res.status})`;
        }
        throw new Error(message);
      }

      setVideos(current => current.filter(v => v.id !== video.id));
      if (selectedVideo?.id === video.id) {
        setSelectedVideo(null);
        setIsEditing(false);
      }
    } catch (err) {
      console.error("Failed to delete video", err);
      alert(err.message || 'Failed to delete video');
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="library-container">
      <div className="header">
        <h1>Generated Shorts</h1>
        <p>Review, edit, and schedule your automated AI news shorts.</p>
      </div>

      {loading ? (
        <p>Loading videos...</p>
      ) : (
        <div className="video-grid">
          {videos.map(v => (
            <div key={v.id} className="video-card" onClick={() => loadVideoDetails(v.id)}>
              <div className="video-thumbnail">
                <button 
                  className="delete-card-btn"
                  onClick={(e) => handleDelete(v, e)}
                  disabled={deletingId === v.id}
                  title="Delete video"
                  aria-label={`Delete ${v.title}`}
                >
                  {deletingId === v.id ? <Loader2 size={16} className="spin" /> : <Trash2 size={16} />}
                </button>
                {/* Fallback to gradient if no thumbnail */}
                <img 
                  src={mediaUrl(v.id, 'thumbnail.png')} 
                  onError={(e) => {
                    e.target.style.display='none';
                    e.target.parentElement.style.background = 'linear-gradient(45deg, #0f172a, #1e293b)';
                  }}
                  alt={v.title}
                />
                
                {activeProgress[v.id] !== undefined ? (
                  <div style={{
                    position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
                    backgroundColor: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)',
                    display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center',
                    zIndex: 10
                  }}>
                    <Loader2 size={32} className="spin" style={{color: '#3b82f6', marginBottom: '1rem'}} />
                    <div style={{color: 'white', fontWeight: 'bold'}}>Rendering... {Math.round(activeProgress[v.id])}%</div>
                    <div style={{width: '80%', height: '8px', background: '#334155', borderRadius: '4px', marginTop: '12px', overflow: 'hidden'}}>
                      <div style={{width: `${activeProgress[v.id]}%`, height: '100%', background: '#3b82f6', borderRadius: '4px', transition: 'width 0.5s ease'}}></div>
                    </div>
                  </div>
                ) : (
                  <div className="play-overlay"><Play fill="white" size={24} /></div>
                )}
              </div>
              <div className="video-info">
                <div className="video-title">{v.title}</div>
                <div className="video-meta">
                  <Clock size={14} />
                  {format(new Date(v.created_at), 'MMM d, yyyy')}
                </div>
                {v.has_video ? (
                  <span className="status-badge status-ready"><CheckCircle size={14}/> Ready</span>
                ) : (
                  <span className="status-badge status-missing"><AlertCircle size={14}/> Script Only</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {selectedVideo && (
        <div className="modal-overlay" onClick={() => setSelectedVideo(null)}>
          <div className="modal-content" style={isEditing ? {maxWidth: '1200px'} : {}} onClick={e => e.stopPropagation()}>
            <div className="modal-video-pane">
              {selectedVideo.has_video ? (
                <video 
                  controls 
                  autoPlay 
                  src={mediaUrl(selectedVideo.id, 'video.mp4')} 
                  style={{ border: '2px solid white', borderRadius: '8px', boxSizing: 'border-box' }}
                />
              ) : (
                <div style={{color: '#94a3b8', textAlign: 'center', padding: '2rem'}}>
                  <AlertCircle size={48} style={{marginBottom: '1rem', opacity: 0.5}} />
                  <p>Video not rendered yet.</p>
                  <p style={{fontSize: '0.85rem', marginTop: '0.5rem'}}>Only script was generated.</p>
                </div>
              )}
            </div>
            
            <div className="modal-info-pane" style={{ overflowY: 'auto' }}>
              <button className="close-btn" onClick={() => setSelectedVideo(null)}>×</button>
              
              {!isEditing ? (
                <>
                  <h2 className="modal-title">{selectedVideo.metadata.title_options[0]}</h2>
                  
                  <div className="metadata-section">
                    <h3>Description & Hashtags</h3>
                    <p style={{fontSize: '0.9rem', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap'}}>
                      {selectedVideo.metadata.description}
                    </p>
                    <div className="tag-list">
                      {selectedVideo.metadata.hashtags.map(t => (
                        <span key={t} className="tag">{t}</span>
                      ))}
                    </div>
                  </div>

                  <div className="metadata-section">
                    <h3>Script Quality ({selectedVideo.quality_report.overall_score}/100)</h3>
                    <p style={{fontSize: '0.9rem', color: 'var(--text-secondary)'}}>
                      Verdict: <strong style={{color: selectedVideo.quality_report.verdict === 'approved' ? 'var(--success)' : 'var(--danger)'}}>
                        {selectedVideo.quality_report.verdict.toUpperCase()}
                      </strong>
                    </p>
                  </div>

                  <div style={{ display: 'flex', gap: '1rem', marginTop: 'auto', marginBottom: '1rem' }}>
                    <button className="btn" style={{ flex: 1, backgroundColor: '#334155' }} onClick={handleEditClick}>
                      <Edit2 size={18} /> Edit & Re-Render
                    </button>
                    <button 
                      className="btn btn-danger"
                      onClick={(e) => handleDelete(selectedVideo, e)}
                      disabled={deletingId === selectedVideo.id}
                    >
                      {deletingId === selectedVideo.id ? <Loader2 size={18} className="spin" /> : <Trash2 size={18} />}
                      Delete
                    </button>
                  </div>

                  <div className="action-bar">
                    <div className="input-group" style={{flex: 1, marginBottom: 0}}>
                      <input 
                        type="datetime-local" 
                        className="input-field" 
                        value={scheduleTime}
                        onChange={e => setScheduleTime(e.target.value)}
                      />
                    </div>
                    <button className="btn btn-primary" onClick={handleSchedule}>
                      <Calendar size={18} /> Schedule in Buffer
                    </button>
                  </div>
                </>
              ) : (
                <div style={{ paddingRight: '1rem', display: 'flex', flexDirection: 'column', gap: '1.5rem', height: '100%' }}>
                  <h2 className="modal-title" style={{ borderBottom: '1px solid #334155', paddingBottom: '1rem' }}>Edit Package</h2>
                  
                  <div>
                    <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 'bold' }}>Script Overrides</label>
                    <textarea 
                      value={editScript}
                      onChange={(e) => setEditScript(e.target.value)}
                      style={{
                        width: '100%',
                        height: '200px',
                        backgroundColor: '#0f172a',
                        border: '1px solid #334155',
                        borderRadius: '8px',
                        color: 'white',
                        padding: '1rem',
                        fontFamily: 'monospace',
                        lineHeight: 1.5,
                        resize: 'vertical'
                      }}
                    />
                  </div>

                  <div>
                    <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 'bold' }}>Custom B-Roll Link (Optional)</label>
                    <input 
                      type="text" 
                      placeholder="YouTube URL..."
                      value={editVideoUrl}
                      onChange={e => setEditVideoUrl(e.target.value)}
                      style={{
                        width: '100%',
                        padding: '0.75rem',
                        backgroundColor: '#0f172a',
                        border: '1px solid #334155',
                        borderRadius: '8px',
                        color: 'white',
                      }}
                    />
                  </div>

                  <div style={{ display: 'flex', gap: '1rem' }}>
                    <div style={{ flex: 1 }}>
                      <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 'bold' }}>Voice</label>
                      <select 
                        value={editVoice}
                        onChange={e => setEditVoice(e.target.value)}
                        style={{
                          width: '100%',
                          padding: '0.75rem',
                          backgroundColor: '#0f172a',
                          border: '1px solid #334155',
                          borderRadius: '8px',
                          color: 'white',
                        }}
                      >
                        <option value="en-US-JennyNeural">Jenny (Natural Female)</option>
                        <option value="en-US-AriaNeural">Aria (Professional Female)</option>
                        <option value="en-US-GuyNeural">Guy (Standard Male)</option>
                        <option value="en-US-ChristopherNeural">Christopher (Natural Male)</option>
                      </select>
                    </div>
                    <div>
                      <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 'bold' }}>Accent Color</label>
                      <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                        <input 
                          type="color" 
                          value={editColor}
                          onChange={e => setEditColor(e.target.value)}
                          style={{ width: '40px', height: '40px', padding: 0, border: 'none', background: 'transparent' }}
                        />
                        <span>{editColor}</span>
                      </div>
                    </div>
                  </div>

                  <div style={{ marginTop: 'auto', display: 'flex', gap: '1rem', paddingTop: '1rem', borderTop: '1px solid #334155' }}>
                    <button 
                      className="btn" 
                      style={{ flex: 1, backgroundColor: '#334155' }}
                      onClick={() => setIsEditing(false)}
                      disabled={isRerendering}
                    >
                      Cancel
                    </button>
                    <button 
                      className="btn btn-primary" 
                      style={{ flex: 2 }}
                      onClick={handleReRender}
                      disabled={isRerendering}
                    >
                      {isRerendering ? <Loader2 size={18} className="spin" /> : <Save size={18} />}
                      {isRerendering ? 'Re-rendering...' : 'Save & Re-Render'}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
