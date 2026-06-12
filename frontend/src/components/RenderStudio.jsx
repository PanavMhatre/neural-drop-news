import React, { useState } from 'react';
import { Upload, Link as LinkIcon, Palette, Mic, Play, Loader2, FileVideo } from 'lucide-react';

export default function RenderStudio() {
  const [topic, setTopic] = useState('');
  const [videoUrl, setVideoUrl] = useState('');
  const [selectedFile, setSelectedFile] = useState(null);
  const [accentColor, setAccentColor] = useState('#ffffff');
  const [voice, setVoice] = useState('en-US-JennyNeural');
  const [isUploading, setIsUploading] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [message, setMessage] = useState(null);

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files[0]) {
      setSelectedFile(e.target.files[0]);
      setVideoUrl(''); // clear URL if file selected
    }
  };

  const handleGenerate = async () => {
    setIsGenerating(true);
    setMessage({ type: 'info', text: 'Preparing generation...' });
    
    try {
      let finalVideoUrl = videoUrl;
      
      // Upload local file first if provided
      if (selectedFile) {
        setIsUploading(true);
        setMessage({ type: 'info', text: 'Uploading custom video file...' });
        const formData = new FormData();
        formData.append('file', selectedFile);
        
        const uploadRes = await fetch('http://localhost:880/api/upload', {
          method: 'POST',
          body: formData,
        });
        
        if (!uploadRes.ok) throw new Error('Failed to upload video');
        const uploadData = await uploadRes.json();
        finalVideoUrl = uploadData.file_path;
        setIsUploading(false);
      }
      
      // Trigger pipeline
      setMessage({ type: 'info', text: 'Triggering background pipeline...' });
      const options = {
        topic: topic || null,
        custom_video_url: finalVideoUrl || null,
        accent_color_hex: accentColor,
        tts_voice: voice
      };

      const res = await fetch('http://localhost:880/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(options)
      });
      
      if (!res.ok) throw new Error('Failed to start generation');
      
      setMessage({ type: 'success', text: 'Generation started successfully! Check the Library tab in a few minutes.' });
      
      // Reset form
      setTopic('');
      setVideoUrl('');
      setSelectedFile(null);
      
    } catch (err) {
      console.error(err);
      setMessage({ type: 'error', text: err.message });
      setIsUploading(false);
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <div style={{ padding: '2rem', maxWidth: '800px', margin: '0 auto' }}>
      <div style={{ marginBottom: '2rem' }}>
        <h1 style={{ fontSize: '2.5rem', fontWeight: 'bold', marginBottom: '0.5rem', color: '#f8fafc' }}>
          Render Studio
        </h1>
        <p style={{ color: '#94a3b8', fontSize: '1.1rem' }}>
          Manually trigger the AI pipeline with custom overrides and media.
        </p>
      </div>

      {message && (
        <div style={{
          padding: '1rem',
          borderRadius: '8px',
          marginBottom: '2rem',
          backgroundColor: message.type === 'error' ? '#7f1d1d' : message.type === 'success' ? '#14532d' : '#1e3a8a',
          color: message.type === 'error' ? '#fca5a5' : message.type === 'success' ? '#bbf7d0' : '#bfdbfe',
          border: `1px solid ${message.type === 'error' ? '#ef4444' : message.type === 'success' ? '#22c55e' : '#3b82f6'}`
        }}>
          {message.text}
        </div>
      )}

      <div style={{ 
        backgroundColor: '#1e293b', 
        padding: '2rem', 
        borderRadius: '12px',
        border: '1px solid #334155',
        display: 'flex',
        flexDirection: 'column',
        gap: '1.5rem'
      }}>
        
        {/* Topic */}
        <div>
          <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: '500', color: '#e2e8f0' }}>
            Story Topic or Source URL (Optional)
          </label>
          <input 
            type="text" 
            placeholder="e.g. Nvidia's new AI chips, OR paste a YouTube/News link..."
            value={topic}
            onChange={e => setTopic(e.target.value)}
            style={{
              width: '100%',
              padding: '0.75rem 1rem',
              backgroundColor: '#0f172a',
              border: '1px solid #334155',
              borderRadius: '8px',
              color: 'white',
              fontSize: '1rem'
            }}
          />
          <p style={{ fontSize: '0.875rem', color: '#64748b', marginTop: '0.5rem' }}>
            Leave blank for autonomous AI discovery. Paste a URL to build a video strictly from that source.
          </p>
        </div>

        <div style={{ height: '1px', backgroundColor: '#334155', margin: '0.5rem 0' }}></div>

        {/* Custom Media */}
        <div>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem', fontWeight: '500', color: '#e2e8f0' }}>
            <FileVideo size={18} />
            Background B-Roll Override
          </label>
          <p style={{ fontSize: '0.875rem', color: '#64748b', marginBottom: '1rem' }}>
            Provide a custom video to use as background b-roll. You can paste a YouTube URL or upload a local file.
          </p>
          
          <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
            <div style={{ flex: 1 }}>
              <div style={{ position: 'relative' }}>
                <LinkIcon size={18} style={{ position: 'absolute', left: '1rem', top: '50%', transform: 'translateY(-50%)', color: '#64748b' }} />
                <input 
                  type="text" 
                  placeholder="Paste YouTube or Twitter URL..."
                  value={videoUrl}
                  onChange={e => { setVideoUrl(e.target.value); setSelectedFile(null); }}
                  disabled={selectedFile !== null}
                  style={{
                    width: '100%',
                    padding: '0.75rem 1rem 0.75rem 2.5rem',
                    backgroundColor: selectedFile ? '#334155' : '#0f172a',
                    border: '1px solid #334155',
                    borderRadius: '8px',
                    color: 'white',
                    fontSize: '1rem',
                    opacity: selectedFile ? 0.5 : 1
                  }}
                />
              </div>
            </div>
            <div style={{ color: '#64748b', fontWeight: 'bold' }}>OR</div>
            <div>
              <input 
                type="file" 
                accept="video/mp4,video/mov" 
                id="file-upload" 
                style={{ display: 'none' }}
                onChange={handleFileChange}
              />
              <label htmlFor="file-upload" style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                padding: '0.75rem 1.5rem',
                backgroundColor: selectedFile ? '#0ea5e9' : '#334155',
                color: 'white',
                borderRadius: '8px',
                cursor: 'pointer',
                fontWeight: '500',
                transition: 'all 0.2s',
                border: '1px solid transparent'
              }}>
                <Upload size={18} />
                {selectedFile ? 'File Selected' : 'Upload File'}
              </label>
            </div>
          </div>
          {selectedFile && (
            <p style={{ fontSize: '0.875rem', color: '#38bdf8', marginTop: '0.5rem' }}>
              Selected: {selectedFile.name} ({(selectedFile.size / 1024 / 1024).toFixed(2)} MB)
            </p>
          )}
        </div>

        <div style={{ height: '1px', backgroundColor: '#334155', margin: '0.5rem 0' }}></div>

        {/* Styling Options */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem' }}>
          <div>
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem', fontWeight: '500', color: '#e2e8f0' }}>
              <Palette size={18} />
              Accent Color
            </label>
            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
              <input 
                type="color" 
                value={accentColor}
                onChange={e => setAccentColor(e.target.value)}
                style={{
                  width: '50px',
                  height: '50px',
                  padding: '0',
                  border: 'none',
                  borderRadius: '8px',
                  cursor: 'pointer',
                  backgroundColor: 'transparent'
                }}
              />
              <span style={{ color: '#cbd5e1', fontFamily: 'monospace', fontSize: '1.1rem' }}>
                {accentColor.toUpperCase()}
              </span>
            </div>
          </div>

          <div>
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem', fontWeight: '500', color: '#e2e8f0' }}>
              <Mic size={18} />
              AI Voice
            </label>
            <select 
              value={voice}
              onChange={e => setVoice(e.target.value)}
              style={{
                width: '100%',
                padding: '0.75rem 1rem',
                backgroundColor: '#0f172a',
                border: '1px solid #334155',
                borderRadius: '8px',
                color: 'white',
                fontSize: '1rem',
                cursor: 'pointer'
              }}
            >
              <option value="en-US-JennyNeural">Jenny (Natural Female)</option>
              <option value="en-US-AriaNeural">Aria (Professional Female)</option>
              <option value="en-US-GuyNeural">Guy (Standard Male)</option>
              <option value="en-US-ChristopherNeural">Christopher (Natural Male)</option>
            </select>
          </div>
        </div>

        {/* Submit Action */}
        <div style={{ marginTop: '1rem' }}>
          <button 
            onClick={handleGenerate}
            disabled={isGenerating || isUploading}
            style={{
              width: '100%',
              padding: '1rem',
              backgroundColor: (isGenerating || isUploading) ? '#334155' : '#10b981',
              color: 'white',
              border: 'none',
              borderRadius: '8px',
              fontSize: '1.2rem',
              fontWeight: 'bold',
              cursor: (isGenerating || isUploading) ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '0.75rem',
              transition: 'background-color 0.2s'
            }}
          >
            {(isGenerating || isUploading) ? <Loader2 size={24} className="spin" /> : <Play size={24} fill="currentColor" />}
            {isUploading ? 'Uploading Custom Video...' : isGenerating ? 'Generating Video...' : 'Generate New Shorts Video'}
          </button>
          
          <style>{`
            @keyframes spin {
              from { transform: rotate(0deg); }
              to { transform: rotate(360deg); }
            }
            .spin {
              animation: spin 1s linear infinite;
            }
          `}</style>
        </div>

      </div>
    </div>
  );
}
