import axios from 'axios';

const api = axios.create({
  baseURL: 'http://localhost:8000/api/v1',
});

export const submitLecture = async (youtubeUrl: string) => {
  const response = await api.post('/lectures', { youtube_url: youtubeUrl });
  return response.data;
};

export const getJobStatus = async (jobId: string) => {
  const response = await api.get(`/jobs/${jobId}`);
  return response.data;
};

export const getLecture = async (lectureId: string) => {
  const response = await api.get(`/lectures/${lectureId}`);
  return response.data;
};

export const getRecentLectures = async () => {
  // Assuming this endpoint exists, if not, we handle it gracefully
  try {
    const response = await api.get('/lectures');
    return response.data;
  } catch {
    return [];
  }
};
