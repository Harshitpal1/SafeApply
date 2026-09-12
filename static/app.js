const profileForm = document.getElementById('profile-form');
const siteName = document.getElementById('site-name');
const searchJobsBtn = document.getElementById('search-jobs');
const jobResults = document.getElementById('job-results');
const approvalSummary = document.getElementById('approval-summary');
const approveSubmitBtn = document.getElementById('approve-submit');
const applicationsTable = document.getElementById('applications-table');
const refreshApplicationsBtn = document.getElementById('refresh-applications');

let pendingApproval = null;

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || JSON.stringify(data));
  }
  return data;
}

profileForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const formData = new FormData(profileForm);
  const payload = Object.fromEntries(formData.entries());
  await api('/profile', { method: 'POST', body: JSON.stringify(payload) });
  alert('Profile saved');
});

searchJobsBtn.addEventListener('click', async () => {
  jobResults.innerHTML = '';
  const jobs = await api('/search-jobs', {
    method: 'POST',
    body: JSON.stringify({ site_name: siteName.value }),
  });

  jobs.forEach((job) => {
    const li = document.createElement('li');
    li.textContent = `${job.job_title} @ ${job.company} (match: ${job.match_score})`;

    const btn = document.createElement('button');
    btn.textContent = 'Fill Application';
    btn.addEventListener('click', () => fillAndValidate(job));

    li.appendChild(document.createTextNode(' '));
    li.appendChild(btn);
    jobResults.appendChild(li);
  });
});

async function fillAndValidate(job) {
  const fillResult = await api('/fill-application', {
    method: 'POST',
    body: JSON.stringify({
      job_title: job.job_title,
      company: job.company,
      site_name: siteName.value,
      listing_url: job.listing_url,
    }),
  });

  const validation = await api('/validate-application', {
    method: 'POST',
    body: JSON.stringify({
      application_id: fillResult.application_id,
      filled_form_json: fillResult.filled_fields,
      job_description_text: job.description,
    }),
  });

  pendingApproval = { application_id: fillResult.application_id };
  approveSubmitBtn.disabled = false;

  approvalSummary.textContent = JSON.stringify(
    {
      job_title: fillResult.job_title,
      company: fillResult.company,
      filled_fields: fillResult.filled_fields,
      field_errors: fillResult.field_errors,
      validation,
    },
    null,
    2,
  );

  await loadApplications();
}

approveSubmitBtn.addEventListener('click', async () => {
  if (!pendingApproval) return;
  await api('/approve-application', {
    method: 'POST',
    body: JSON.stringify(pendingApproval),
  });
  pendingApproval = null;
  approveSubmitBtn.disabled = true;
  await loadApplications();
});

async function loadApplications() {
  const rows = await api('/applications');
  applicationsTable.innerHTML = '';
  rows.forEach((row) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${row.id}</td>
      <td>${row.job_title}</td>
      <td>${row.company}</td>
      <td>${row.match_score}</td>
      <td>${row.status}</td>
      <td>${row.flag_reason || ''}</td>
      <td>${row.updated_at}</td>
    `;
    applicationsTable.appendChild(tr);
  });
}

refreshApplicationsBtn.addEventListener('click', loadApplications);
loadApplications();
