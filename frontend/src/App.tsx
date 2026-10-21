import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, useNavigate, useParams } from 'react-router-dom';
import { submitLecture, getJobStatus, getLecture } from './api';
import { motion } from 'framer-motion';
import { BrainCircuit, Loader2, Play, FileText, CheckCircle2, Download } from 'lucide-react';

function Landing() {
  const [url, setUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url) return;
    setLoading(true);
    try {
      const data = await submitLecture(url);
      navigate(`/processing/${data.job_id}/${data.lecture_id}`);
    } catch (err) {
      alert("Failed to submit lecture.");
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-4">
      <motion.div 
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="text-center mb-12"
      >
        <div className="flex items-center justify-center gap-3 mb-6">
          <BrainCircuit className="w-12 h-12 text-primary drop-shadow-[0_0_15px_rgba(59,130,246,0.5)]" />
          <h1 className="text-4xl font-bold tracking-tight">Lecture Notes AI</h1>
        </div>
        <p className="text-zinc-400 text-lg">Digest any long-form video in seconds.</p>
      </motion.div>

      <form onSubmit={handleSubmit} className="w-full max-w-2xl relative">
        <div className="absolute inset-y-0 left-4 flex items-center pointer-events-none">
          <Play className="w-5 h-5 text-zinc-500" />
        </div>
        <input 
          type="url" 
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="Paste YouTube URL here..." 
          className="w-full bg-card border border-border rounded-full py-4 pl-12 pr-32 text-lg focus:outline-none focus:ring-2 focus:ring-primary/50 transition-all"
          required
        />
        <button 
          type="submit" 
          disabled={loading}
          className="absolute right-2 top-2 bottom-2 bg-primary hover:bg-blue-600 text-white px-6 rounded-full font-medium flex items-center transition-colors disabled:opacity-50"
        >
          {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : "Process"}
        </button>
      </form>
    </div>
  );
}

const STAGES = ['metadata', 'transcript_acquisition', 'transcript_pipeline', 'fast_notes', 'completed'];
const STAGE_LABELS: Record<string, string> = {
  'pending': 'Initializing Job...',
  'metadata': 'Fetching Video Metadata...',
  'transcript_acquisition': 'Downloading Audio Stream...',
  'transcript_pipeline': 'Transcribing Speech-to-Text...',
  'fast_notes': 'AI Synthesizing Notes (Parallel Chunking)...',
  'visual_analysis': 'Skipped (Disabled)',
  'completed': 'Done!'
};

function Processing() {
  const { jobId, lectureId } = useParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState<any>(null);

  useEffect(() => {
    if (!jobId) return;
    const interval = setInterval(async () => {
      try {
        const data = await getJobStatus(jobId);
        setStatus(data);
        if (data.status === 'completed') {
          clearInterval(interval);
          setTimeout(() => navigate(`/lecture/${lectureId}`), 1000);
        } else if (data.status === 'failed') {
          clearInterval(interval);
          alert("Job failed!");
        }
      } catch (err) {
        console.error(err);
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [jobId, lectureId, navigate]);

  const currentStageIndex = status ? STAGES.indexOf(status.stage) : -1;

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-4">
      <div className="w-full max-w-xl bg-card border border-border rounded-2xl p-8 shadow-xl">
        <h2 className="text-2xl font-bold mb-8 text-center flex items-center justify-center gap-2">
          <BrainCircuit className="w-6 h-6 text-primary animate-pulse" />
          Processing Lecture
        </h2>

        <div className="space-y-6">
          {STAGES.map((s, i) => {
            const isActive = s === status?.stage;
            const isPast = currentStageIndex > i || status?.status === 'completed';
            
            return (
              <div key={s} className="flex items-center gap-4">
                <div className={`w-8 h-8 rounded-full flex items-center justify-center border-2 transition-colors ${
                  isPast ? 'bg-primary border-primary text-white' : 
                  isActive ? 'border-primary text-primary animate-pulse' : 
                  'border-zinc-700 text-zinc-700'
                }`}>
                  {isPast ? <CheckCircle2 className="w-5 h-5" /> : (i + 1)}
                </div>
                <span className={`text-lg transition-colors ${
                  isActive ? 'text-white font-medium' : 
                  isPast ? 'text-zinc-400' : 'text-zinc-600'
                }`}>
                  {STAGE_LABELS[s] || s}
                </span>
                {isActive && <Loader2 className="w-5 h-5 text-primary animate-spin ml-auto" />}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function Results() {
  const { lectureId } = useParams();
  const [lecture, setLecture] = useState<any>(null);

  useEffect(() => {
    if (lectureId) {
      getLecture(lectureId).then(setLecture).catch(console.error);
    }
  }, [lectureId]);

  if (!lecture) return <div className="min-h-screen flex items-center justify-center"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>;

  return (
    <div className="min-h-screen max-w-4xl mx-auto p-8">
      <div className="flex justify-between items-start mb-12 pb-8 border-b border-border">
        <div>
          <h1 className="text-3xl font-bold mb-2">Lecture Notes</h1>
          <a href={lecture.original_url} target="_blank" rel="noreferrer" className="text-primary hover:underline">
            View Source Video
          </a>
        </div>
        <a 
          href={`http://localhost:8000/api/v1/lectures/${lectureId}/pdf`}
          target="_blank"
          download
          className="bg-primary hover:bg-blue-600 text-white px-6 py-3 rounded-lg font-medium flex items-center gap-2 transition-colors"
        >
          <Download className="w-5 h-5" />
          Download PDF
        </a>
      </div>

      <div className="prose prose-invert max-w-none prose-headings:text-primary prose-a:text-blue-400">
        {/* Simple rendering of the JSON for now. A real markdown parser could be added here. */}
        {lecture.notes && lecture.notes.length > 0 ? (
          <div>
            <h2 className="text-2xl font-bold mb-4">{lecture.notes[0].content_json?.lecture_title}</h2>
            <p className="text-lg text-zinc-300 mb-8">{lecture.notes[0].content_json?.overview}</p>
            
            <div className="space-y-8">
              {lecture.notes[0].content_json?.sections?.map((sec: any, i: number) => (
                <div key={i} className="bg-card border border-border p-6 rounded-xl">
                  <h3 className="text-xl font-bold mb-2 flex items-center justify-between">
                    {sec.title}
                    <span className="text-sm font-normal text-zinc-500 bg-black/50 px-3 py-1 rounded-full">{sec.timestamp}</span>
                  </h3>
                  <p className="text-zinc-300 mb-4">{sec.summary}</p>
                  
                  {sec.key_takeaways?.length > 0 && (
                    <ul className="list-disc pl-5 space-y-1 text-zinc-400">
                      {sec.key_takeaways.map((point: string, j: number) => (
                        <li key={j}>{point}</li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </div>
          </div>
        ) : (
          <p>No notes found.</p>
        )}
      </div>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/processing/:jobId/:lectureId" element={<Processing />} />
        <Route path="/lecture/:lectureId" element={<Results />} />
      </Routes>
    </BrowserRouter>
  );
}
