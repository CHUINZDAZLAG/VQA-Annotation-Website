import React from 'react';
import { useOutletContext } from 'react-router-dom';

export default function ReviewerDashboard() {
  const { user } = useOutletContext();

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-950 px-6 text-white">
      <section className="text-center">
        <h1 className="text-3xl font-semibold">Welcome, {user.name}</h1>
        <p className="mt-3 text-slate-300">System role: {user.system_role}</p>
      </section>
    </main>
  );
}
