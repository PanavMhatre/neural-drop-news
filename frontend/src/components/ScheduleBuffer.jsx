import React, { useState, useEffect } from 'react';
import { format, parseISO } from 'date-fns';
import { Clock } from 'lucide-react';

export default function ScheduleBuffer() {
  const [schedule, setSchedule] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchSchedule();
  }, []);

  const fetchSchedule = async () => {
    try {
      const res = await fetch('http://localhost:880/api/schedule');
      const data = await res.json();
      setSchedule(data.scheduled || []);
    } catch (err) {
      console.error("Failed to fetch schedule", err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="library-container">
      <div className="header">
        <h1>Schedule Buffer</h1>
        <p>Upcoming Buffer posts for NeuralDropBits.</p>
      </div>

      {loading ? (
        <p>Loading schedule...</p>
      ) : schedule.length === 0 ? (
        <div style={{textAlign: 'center', padding: '4rem', color: 'var(--text-secondary)'}}>
          <Clock size={48} style={{opacity: 0.3, marginBottom: '1rem'}} />
          <p>No videos scheduled yet.</p>
          <p style={{fontSize: '0.85rem'}}>Go to the Library to add videos to the queue.</p>
        </div>
      ) : (
        <div className="schedule-list">
          {schedule.map(item => {
            const date = parseISO(item.scheduled_time);
            return (
              <div key={item.package_id} className="schedule-item">
                <div className="schedule-time">
                  <span className="schedule-date">{format(date, 'MMM d')}</span>
                  <span className="schedule-hour">{format(date, 'h:mm a')}</span>
                </div>
                
                <div style={{display: 'flex', gap: '1.5rem', alignItems: 'center', flex: 1}}>
                  <div style={{
                    width: '60px', 
                    height: '100px', 
                    background: '#1e293b', 
                    borderRadius: '8px',
                    overflow: 'hidden',
                    position: 'relative'
                  }}>
                    <img 
                      src={`http://localhost:880/media/${item.package_id}/thumbnail.png?t=${Date.now()}`}
                      style={{width: '100%', height: '100%', objectFit: 'cover'}}
                      onError={(e) => e.target.style.display='none'}
                      alt=""
                    />
                  </div>
                  
                  <div style={{flex: 1}}>
                    <h3 style={{fontSize: '1.1rem', marginBottom: '0.25rem'}}>{item.package_id.split('_').slice(1).join(' ')}</h3>
                    <div style={{display: 'flex', gap: '1rem', alignItems: 'center', flexWrap: 'wrap'}}>
                      <span className={`status-badge ${item.status === 'buffer_failed' ? 'status-missing' : 'status-ready'}`}>
                        {item.status.toUpperCase()}
                      </span>
                      {item.buffer_channel_name && (
                        <span className="status-badge status-ready">
                          {item.buffer_channel_name}
                        </span>
                      )}
                      <span style={{fontSize: '0.85rem', color: 'var(--text-secondary)'}}>
                        ID: {item.package_id}
                      </span>
                    </div>
                    {item.buffer_post_id && (
                      <p style={{fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.5rem'}}>
                        Buffer post: {item.buffer_post_id}
                      </p>
                    )}
                    {item.buffer_error && (
                      <p style={{fontSize: '0.8rem', color: 'var(--danger)', marginTop: '0.5rem'}}>
                        {item.buffer_error}
                      </p>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
