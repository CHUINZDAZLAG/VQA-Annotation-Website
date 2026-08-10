import React from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import ProtectedRoute from './components/ProtectedRoute';
import AdminDashboard from './pages/AdminDashboard';
import AdminLogin from './pages/AdminLogin';
import AdminTaskCreate from './pages/AdminTaskCreate';
import AdminTaskDetail from './pages/AdminTaskDetail';
import AdminTaskList from './pages/AdminTaskList';
import AdminTaskResults from './pages/AdminTaskResults';
import AdminUserList from './pages/AdminUserList';
import AnnotatorDashboard from './pages/AnnotatorDashboard';
import AnnotationWorkspace from './pages/AnnotationWorkspace';
import BlindWorkspace from './pages/BlindWorkspace';
import Login from './pages/Login';
import ReviewerDashboard from './pages/ReviewerDashboard';
import ReviewWorkspace from './pages/ReviewWorkspace';
import UserTaskDetail from './pages/UserTaskDetail';
import UserTaskList from './pages/UserTaskList';

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/admin/login" element={<AdminLogin />} />
      <Route element={<ProtectedRoute allowedRole="ADMIN" portal="admin" />}>
        <Route path="/admin" element={<AdminDashboard />} />
        <Route path="/admin/tasks" element={<AdminTaskList />} />
        <Route path="/admin/tasks/create" element={<AdminTaskCreate />} />
        <Route path="/admin/tasks/:taskId" element={<AdminTaskDetail />} />
        <Route path="/admin/tasks/:taskId/results" element={<AdminTaskResults />} />
        <Route path="/admin/users" element={<AdminUserList />} />
      </Route>
      <Route element={<ProtectedRoute allowedRole="USER" />}>
        <Route path="/annotator" element={<AnnotatorDashboard />} />
        <Route path="/reviewer" element={<ReviewerDashboard />} />
        <Route path="/tasks" element={<UserTaskList />} />
        <Route path="/tasks/:taskId" element={<UserTaskDetail />} />
        <Route path="/tasks/:taskId/annotate" element={<AnnotationWorkspace />} />
        <Route path="/tasks/:taskId/blind" element={<BlindWorkspace />} />
        <Route path="/tasks/:taskId/review" element={<ReviewWorkspace />} />
      </Route>
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}
