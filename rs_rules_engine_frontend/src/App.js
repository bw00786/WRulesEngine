import React, { useState, useEffect } from "react";
import axios from "axios";
import { 
    Container, 
    Typography, 
    Button, 
    Box, 
    CircularProgress, 
    Snackbar, 
    Alert,
    Stack,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    Paper
} from "@mui/material";
import FileUploadIcon from '@mui/icons-material/FileUpload';
import AssessmentIcon from '@mui/icons-material/Assessment';
import { ErrorBoundary } from 'react-error-boundary';
import config from './config';

function App() {
    const [file, setFile] = useState(null);
    const [loading, setLoading] = useState(false);
    const [message, setMessage] = useState("");
    const [openSnackbar, setOpenSnackbar] = useState(false);
    const [severity, setSeverity] = useState("success");
    const [reportId, setReportId] = useState(null);
    const [reportData, setReportData] = useState(null);
    const [validationErrors, setValidationErrors] = useState([]);
    const [recentReports, setRecentReports] = useState([]);

    // Error boundary fallback component
    const ErrorFallback = ({ error, resetErrorBoundary }) => (
        <Alert severity="error" sx={{ mt: 2 }}>
            Error rendering report: {error.message}
            <Button onClick={resetErrorBoundary} sx={{ ml: 2 }}>Try Again</Button>
        </Alert>
    );

    // Fetch recent reports on component mount
    useEffect(() => {
        fetchRecentReports();
    }, []);

    const fetchRecentReports = async () => {
        try {
            const response = await axios.get(`${config.API_URL}/rules/upload-reports/`);
            setRecentReports(response.data);
        } catch (error) {
            console.error("Error fetching recent reports:", error);
            setSeverity("error");
            setMessage("Failed to load recent reports");
            setOpenSnackbar(true);
        }
    };

    const handleFileChange = (event) => {
        const selectedFile = event.target.files[0];
        if (!selectedFile) return;

        const validExtensions = [".xls", ".xlsx", ".json"];
        const fileExt = selectedFile.name.slice(selectedFile.name.lastIndexOf(".")).toLowerCase();
        
        if (!validExtensions.includes(fileExt)) {
            setSeverity("error");
            setMessage("Invalid file format! Please upload Excel or JSON.");
            setOpenSnackbar(true);
            return;
        }

        setFile(selectedFile);
        setReportData(null);
        setValidationErrors([]);
    };

    const handleUpload = async () => {
        if (!file) {
            setSeverity("error");
            setMessage("Please select a file to upload.");
            setOpenSnackbar(true);
            return;
        }

        setLoading(true);
        const formData = new FormData();
        formData.append("file", file);

        try {
            const response = await axios.post(`${config.API_URL}/upload_rules/`, formData, {
                headers: { "Content-Type": "multipart/form-data" },
            });
            
            console.log("Response data:", response.data);
            
            // Handle different response structures
            if (response.data.status === 'error') {
                // Handle validation error case
                setSeverity("error");
                setMessage(response.data.message || "Rule validation failed");
                setValidationErrors(response.data.validation_errors || []);
                
                // Create a minimal report data structure for the error case
                setReportData({
                    id: response.data.reportId || "error",
                    filename: file.name,
                    context: response.data.context || 'default',
                    status: 'error',
                    errors: response.data.validation_errors || []
                });
            } else {
                // Handle success case
                setReportId(response.data.reportId);
                setReportData({
                    ...response.data,
                    id: response.data.reportId,
                    status: 'success',
                    stats: response.data.stats || {},
                    context: response.data.context || 'default'
                });
                
                setSeverity("success");
                const successfulUploads = response.data.stats?.successful_uploads || 0;
                setMessage(`File processed successfully! ${successfulUploads} rules added.`);
                setValidationErrors([]);
            }
            
            await fetchRecentReports();
        } catch (error) {
            console.error("Upload error:", error);
            
            // Check if the response contains validation errors
            if (error.response?.data?.validation_errors) {
                setSeverity("error");
                setMessage(error.response.data.message || "Rule validation failed");
                setValidationErrors(error.response.data.validation_errors || []);
                
                // Create a minimal report data structure for the error case
                setReportData({
                    id: "error",
                    filename: file.name,
                    status: 'error',
                    errors: error.response.data.validation_errors || []
                });
            } else {
                const errorMessage = error.response?.data?.detail || 
                    error.response?.data?.message || 
                    "Error processing file. Please try again.";
                setSeverity("error");
                setMessage(errorMessage);
                setReportData(null);
                setValidationErrors([]);
            }
        } finally {
            setLoading(false);
            setOpenSnackbar(true);
        }
    };

    const viewReport = async (id) => {
        try {
            const response = await axios.get(`${config.API_URL}/rules/upload-report/${id}`);
            
            // Check if response contains validation errors
            if (response.data.validation_errors || response.data.errors) {
                setValidationErrors(response.data.validation_errors || response.data.errors || []);
                setReportData({
                    ...response.data,
                    id: response.data.id || id,
                    status: response.data.status || 'error',
                    errors: response.data.validation_errors || response.data.errors || [],
                    context: response.data.context || 'default'
                });
            } else {
                setReportData({
                    ...response.data,
                    id: response.data.id || id,
                    status: response.data.status || 'success',
                    stats: response.data.stats || {},
                    context: response.data.context || 'default'
                });
                setValidationErrors([]);
            }
            
            setReportId(id);
        } catch (error) {
            setSeverity("error");
            setMessage("Error fetching report. Please try again.");
            setOpenSnackbar(true);
        }
    };

    const renderReportDetails = () => {
        if (!reportData) return null;

        return (
            <Box sx={{ mt: 4 }}>
                <Typography variant="h5" sx={{ mb: 2 }}>Report Details</Typography>
                
                <TableContainer component={Paper}>
                    <Table>
                        <TableBody>
                            <TableRow>
                                <TableCell><strong>Report ID</strong></TableCell>
                                <TableCell>{reportData.id}</TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell><strong>Filename</strong></TableCell>
                                <TableCell>{reportData.filename}</TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell><strong>Status</strong></TableCell>
                                <TableCell>
                                    <Typography color={reportData.status === 'error' ? 'error' : 'success'}>
                                        {reportData.status === 'error' ? 'Failed' : 'Success'}
                                    </Typography>
                                </TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell><strong>Context</strong></TableCell>
                                <TableCell>{reportData.context}</TableCell>
                            </TableRow>
                            
                            {reportData.status !== 'error' && (
                                <>
                                    <TableRow>
                                        <TableCell><strong>Processing Time</strong></TableCell>
                                        <TableCell>{reportData.processing_time?.toFixed(2)}s</TableCell>
                                    </TableRow>
                                    <TableRow>
                                        <TableCell><strong>Success Rate</strong></TableCell>
                                        <TableCell>
                                            {(reportData.stats?.success_rate * 100)?.toFixed(1) || '0.0'}%
                                        </TableCell>
                                    </TableRow>
                                    <TableRow>
                                        <TableCell><strong>Rules Processed</strong></TableCell>
                                        <TableCell>{reportData.stats?.total_rules_processed || 0}</TableCell>
                                    </TableRow>
                                    <TableRow>
                                        <TableCell><strong>Successful Uploads</strong></TableCell>
                                        <TableCell>{reportData.stats?.successful_uploads || 0}</TableCell>
                                    </TableRow>
                                    <TableRow>
                                        <TableCell><strong>Failed Uploads</strong></TableCell>
                                        <TableCell>{reportData.stats?.failed_uploads || 0}</TableCell>
                                    </TableRow>
                                </>
                            )}
                        </TableBody>
                    </Table>
                </TableContainer>

                {/* Show validation errors section */}
                {(validationErrors.length > 0 || reportData.errors?.length > 0) && (
                    <Box sx={{ mt: 3 }}>
                        <Typography variant="h6" sx={{ mb: 2 }} color="error">
                            Validation Errors
                        </Typography>
                        <TableContainer component={Paper}>
                            <Table>
                                <TableHead>
                                    <TableRow>
                                        <TableCell>Row</TableCell>
                                        <TableCell>Rule Name</TableCell>
                                        <TableCell>Error Type</TableCell>
                                        <TableCell>Message</TableCell>
                                    </TableRow>
                                </TableHead>
                                <TableBody>
                                    {(validationErrors.length > 0 ? validationErrors : reportData.errors || []).map((error, index) => (
                                        <TableRow key={index}>
                                            <TableCell>{error.row !== undefined ? error.row : 'N/A'}</TableCell>
                                            <TableCell>{error.rule_name || 'Unknown'}</TableCell>
                                            <TableCell>{error.error_type || 'Error'}</TableCell>
                                            <TableCell>{error.error_message || error.message || 'Unknown error'}</TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </TableContainer>
                    </Box>
                )}

                {reportData.test_results?.length > 0 && (
                    <Box sx={{ mt: 3 }}>
                        <Typography variant="h6" sx={{ mb: 2 }}>Test Results</Typography>
                        <TableContainer component={Paper}>
                            <Table>
                                <TableHead>
                                    <TableRow>
                                        <TableCell>Rule Name</TableCell>
                                        <TableCell>Status</TableCell>
                                        <TableCell>Details</TableCell>
                                    </TableRow>
                                </TableHead>
                                <TableBody>
                                    {reportData.test_results.map((test, index) => (
                                        <TableRow key={index}>
                                            <TableCell>{test.rule_name}</TableCell>
                                            <TableCell>
                                                {test.evaluation_result?.can_evaluate ? 
                                                    'Valid' : 'Invalid'}
                                            </TableCell>
                                            <TableCell>
                                                {test.evaluation_result?.error || 
                                                 `${test.evaluation_result?.matched_conditions?.length || 0} conditions matched`}
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </TableContainer>
                    </Box>
                )}
            </Box>
        );
    };

    return (
        <Container maxWidth="lg" sx={{ mt: 5 }}>
            <Typography variant="h3" sx={{ fontWeight: "bold", mb: 3, textAlign: "center" }}>
                Rules Engine Dashboard
            </Typography>
            
            <Box sx={{ display: 'flex', gap: 4, flexDirection: { xs: 'column', md: 'row' } }}>
                <Box sx={{ flex: 1 }}>
                    <Box sx={{ border: "1px dashed #ccc", p: 3, borderRadius: 2, textAlign: "center" }}>
                        <input 
                            type="file" 
                            onChange={handleFileChange} 
                            accept=".xls,.xlsx,.json" 
                            style={{ marginBottom: 16 }}
                        />
                        <Typography variant="body2" color="textSecondary">
                            Supported formats: Excel (.xls, .xlsx) or JSON
                        </Typography>
                    </Box>
                    
                    <Stack direction="row" spacing={2} justifyContent="center" sx={{ mt: 3 }}>
                        <Button
                            variant="contained"
                            color="primary"
                            onClick={handleUpload}
                            disabled={loading}
                            startIcon={loading ? <CircularProgress size={24} /> : <FileUploadIcon />}
                            sx={{ minWidth: 200 }}
                        >
                            {loading ? 'Processing...' : 'Upload Rules'}
                        </Button>
                    </Stack>

                    {recentReports.length > 0 && (
                        <Box sx={{ mt: 4 }}>
                            <Typography variant="h6" sx={{ mb: 2 }}>Recent Uploads</Typography>
                            <TableContainer component={Paper}>
                                <Table>
                                    <TableHead>
                                        <TableRow>
                                            <TableCell>Context</TableCell>
                                            <TableCell>Filename</TableCell>
                                            <TableCell>Upload Time</TableCell>
                                            <TableCell>Action</TableCell>
                                        </TableRow>
                                    </TableHead>
                                    <TableBody>
                                        {recentReports.map((report) => (
                                            <TableRow key={report.id}>
                                                <TableCell>{report.context || 'default'}</TableCell>
                                                <TableCell>{report.filename}</TableCell>
                                                <TableCell>
                                                    {new Date(report.upload_timestamp).toLocaleString()}
                                                </TableCell>
                                                <TableCell>
                                                    <Button
                                                        size="small"
                                                        startIcon={<AssessmentIcon />}
                                                        onClick={() => viewReport(report.id)}
                                                        variant="outlined"
                                                    >
                                                        Details
                                                    </Button>
                                                </TableCell>
                                            </TableRow>
                                        ))}
                                    </TableBody>
                                </Table>
                            </TableContainer>
                        </Box>
                    )}
                </Box>

                <Box sx={{ flex: 1 }}>
                    <ErrorBoundary
                        FallbackComponent={ErrorFallback}
                        onReset={() => {
                            setReportData(null);
                            setValidationErrors([]);
                        }}
                        resetKeys={[reportData]}
                    >
                        {renderReportDetails()}
                    </ErrorBoundary>
                </Box>
            </Box>

            <Snackbar 
                open={openSnackbar} 
                autoHideDuration={6000} 
                onClose={() => setOpenSnackbar(false)}
                anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
            >
                <Alert 
                    severity={severity} 
                    onClose={() => setOpenSnackbar(false)}
                    sx={{ width: '100%' }}
                >
                    {message}
                </Alert>
            </Snackbar>
        </Container>
    );
}

export default App;