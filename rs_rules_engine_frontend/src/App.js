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
import config from './config';

function App() {
    const [file, setFile] = useState(null);
    const [loading, setLoading] = useState(false);
    const [message, setMessage] = useState("");
    const [openSnackbar, setOpenSnackbar] = useState(false);
    const [severity, setSeverity] = useState("success");
    const [reportId, setReportId] = useState(null);
    const [reportData, setReportData] = useState(null);
    const [recentReports, setRecentReports] = useState([]);

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
        }
    };

    const handleFileChange = (event) => {
        const selectedFile = event.target.files[0];

        if (!selectedFile) return;

        if (!selectedFile.name.endsWith(".xls") && !selectedFile.name.endsWith(".xlsx")) {
            setSeverity("error");
            setMessage("Invalid file format! Please upload an Excel file.");
            setOpenSnackbar(true);
            return;
        }

        setFile(selectedFile);
        setReportData(null);
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
            const response = await axios.post(`${config.API_URL}/rules/upload-report/`, formData, {
                headers: { "Content-Type": "multipart/form-data" },
            });

            setReportId(response.data.report_id);
            setReportData(response.data);
            setSeverity("success");
            setMessage("File processed successfully! Report generated.");
            
            // Refresh the recent reports list
            await fetchRecentReports();
        } catch (error) {
            setSeverity("error");
            setMessage(error.response?.data?.detail || "Error processing file. Please try again.");
            console.error("Error:", error);
        } finally {
            setLoading(false);
            setOpenSnackbar(true);
        }
    };

    const viewReport = async (id) => {
        try {
            const response = await axios.get(`${config.API_URL}/rules/upload-report/${id}`);
            setReportData(response.data);
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
                                <TableCell>{reportData.report_id}</TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell><strong>Filename</strong></TableCell>
                                <TableCell>{reportData.filename}</TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell><strong>Processing Time</strong></TableCell>
                                <TableCell>{reportData.processing_time.toFixed(2)}s</TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell><strong>Success Rate</strong></TableCell>
                                <TableCell>{(reportData.stats.success_rate * 100).toFixed(1)}%</TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell><strong>Rules Processed</strong></TableCell>
                                <TableCell>{reportData.stats.total_rules_processed}</TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell><strong>Successful Uploads</strong></TableCell>
                                <TableCell>{reportData.stats.successful_uploads}</TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell><strong>Failed Uploads</strong></TableCell>
                                <TableCell>{reportData.stats.failed_uploads}</TableCell>
                            </TableRow>
                        </TableBody>
                    </Table>
                </TableContainer>

                {reportData.errors.length > 0 && (
                    <Box sx={{ mt: 3 }}>
                        <Typography variant="h6" sx={{ mb: 2 }}>Errors</Typography>
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
                                    {reportData.errors.map((error, index) => (
                                        <TableRow key={index}>
                                            <TableCell>{error.row}</TableCell>
                                            <TableCell>{error.rule_name}</TableCell>
                                            <TableCell>{error.error_type}</TableCell>
                                            <TableCell>{error.error_message}</TableCell>
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
                RS Rules Engine
            </Typography>
            
            <Box sx={{ display: 'flex', gap: 4 }}>
                <Box sx={{ flex: 1 }}>
                    <Box sx={{ border: "1px dashed gray", padding: 3, borderRadius: 2, textAlign: "center" }}>
                        <input type="file" onChange={handleFileChange} accept=".xls,.xlsx" />
                    </Box>
                    <Stack direction="row" spacing={2} justifyContent="center" sx={{ mt: 3 }}>
                        <Button
                            variant="contained"
                            color="primary"
                            onClick={handleUpload}
                            disabled={loading}
                            startIcon={loading ? <CircularProgress size={24} /> : <FileUploadIcon />}
                        >
                            Upload and Process
                        </Button>
                    </Stack>

                    {recentReports.length > 0 && (
                        <Box sx={{ mt: 4 }}>
                            <Typography variant="h6" sx={{ mb: 2 }}>Recent Reports</Typography>
                            <TableContainer component={Paper}>
                                <Table>
                                    <TableHead>
                                        <TableRow>
                                            <TableCell>Report ID</TableCell>
                                            <TableCell>Filename</TableCell>
                                            <TableCell>Success Rate</TableCell>
                                            <TableCell>Action</TableCell>
                                        </TableRow>
                                    </TableHead>
                                    <TableBody>
                                        {recentReports.map((report) => (
                                            <TableRow key={report.report_id}>
                                                <TableCell>{report.report_id}</TableCell>
                                                <TableCell>{report.filename}</TableCell>
                                                <TableCell>
                                                    {(report.stats.success_rate * 100).toFixed(1)}%
                                                </TableCell>
                                                <TableCell>
                                                    <Button
                                                        size="small"
                                                        startIcon={<AssessmentIcon />}
                                                        onClick={() => viewReport(report.report_id)}
                                                    >
                                                        View
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
                    {renderReportDetails()}
                </Box>
            </Box>

            <Snackbar open={openSnackbar} autoHideDuration={4000} onClose={() => setOpenSnackbar(false)}>
                <Alert severity={severity} onClose={() => setOpenSnackbar(false)}>
                    {message}
                </Alert>
            </Snackbar>
        </Container>
    );
}

export default App;