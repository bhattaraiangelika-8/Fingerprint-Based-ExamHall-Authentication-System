/**
 * Dashboard — search and delete functionality
 */
document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('search-input');
    if (searchInput) {
        searchInput.addEventListener('input', function() {
            const query = this.value.toLowerCase().trim();
            const rows = document.querySelectorAll('#students-table tbody tr');
            rows.forEach(function(row) {
                const searchData = row.getAttribute('data-search') || '';
                row.style.display = searchData.indexOf(query) !== -1 ? '' : 'none';
            });
        });
    }
});

function deleteStudent(id, name) {
    if (!confirm('Are you sure you want to delete "' + name + '"? This action cannot be undone.')) return;

    fetch('/api/students/' + id + '/', {
        method: 'DELETE',
        headers: { 'X-CSRFToken': getCsrfToken() }
    })
    .then(function(response) {
        if (response.ok) {
            showToast('Student deleted successfully', 'success');
            setTimeout(function() { location.reload(); }, 1000);
        } else {
            showToast('Failed to delete student', 'error');
        }
    })
    .catch(function(err) {
        showToast('Error: ' + err.message, 'error');
    });
}
