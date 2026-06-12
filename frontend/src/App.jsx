import React, { useState } from 'react';
import { Layers, CalendarClock, Settings, Sparkles } from 'lucide-react';
import VideoLibrary from './components/VideoLibrary';
import ScheduleBuffer from './components/ScheduleBuffer';

import RenderStudio from './components/RenderStudio';

export default function App() {
  const [activeTab, setActiveTab] = useState('library');

  return (
    <>
      <div className="sidebar">
        <div className="logo">
          <Sparkles color="var(--accent)" size={24} />
          TechPulse AI
        </div>
        
        <div className="nav-links">
          <div 
            className={`nav-link ${activeTab === 'library' ? 'active' : ''}`}
            onClick={() => setActiveTab('library')}
          >
            <Layers size={20} />
            Library
          </div>
          <div 
            className={`nav-link ${activeTab === 'schedule' ? 'active' : ''}`}
            onClick={() => setActiveTab('schedule')}
          >
            <CalendarClock size={20} />
            Schedule Buffer
          </div>
          <div 
            className={`nav-link ${activeTab === 'settings' ? 'active' : ''}`}
            onClick={() => setActiveTab('settings')}
          >
            <Settings size={20} />
            Render Studio
          </div>
        </div>
      </div>

      <div className="main-content">
        {activeTab === 'library' && <VideoLibrary />}
        {activeTab === 'schedule' && <ScheduleBuffer />}
        {activeTab === 'settings' && <RenderStudio />}
      </div>
    </>
  );
}
