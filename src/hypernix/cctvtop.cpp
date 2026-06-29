#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <iostream>
#include <fstream>
#include <string>
#include <vector>
#include <thread>
#include <chrono>
#include <cmath>
#include <csignal>
#include <termios.h>
#include <unistd.h>
#include <regex>
#include <deque>
#include <iomanip>

volatile sig_atomic_t g_running = 1;

void signal_handler(int signum) {
    g_running = 0;
}

struct TermLock {
    struct termios orig_termios;
    bool locked;
    TermLock() : locked(false) {}
    void lock() {
        if (tcgetattr(STDIN_FILENO, &orig_termios) != -1) {
            struct termios raw = orig_termios;
            raw.c_lflag &= ~(ECHO | ICANON);
            tcsetattr(STDIN_FILENO, TCSAFLUSH, &raw);
            locked = true;
        }
        std::cout << "\033[?25l"; // hide cursor
    }
    void unlock() {
        if (locked) {
            tcsetattr(STDIN_FILENO, TCSAFLUSH, &orig_termios);
        }
        std::cout << "\033[?25h"; // show cursor
        std::cout << "\033[0m\n"; // reset colors
    }
};

struct DataPoint {
    int step;
    double loss;
    double lr;
    double tput;
};

// Colors
const char* COLOR_DARK_GREEN = "\033[38;2;0;100;0m";
const char* COLOR_MED_GREEN = "\033[38;2;0;200;0m";
const char* COLOR_BLACK_BG = "\033[40m";
const char* COLOR_RESET = "\033[0m";

std::vector<DataPoint> parse_log(const std::string& path) {
    std::vector<DataPoint> data;
    std::ifstream file(path);
    if (!file.is_open()) return data;

    std::string line;
    std::regex loss_re("loss[=:]\\s*([0-9]*\\.?[0-9]+)");
    std::regex step_re("step[=\\s]+([0-9]+)");
    std::regex lr_re("lr[=:]\\s*([0-9]*\\.?[0-9]+[eE]?-?[0-9]*)");

    while (std::getline(file, line)) {
        std::smatch m_loss, m_step, m_lr;
        DataPoint pt = {0, 0.0, 0.0, 0.0};
        bool found = false;

        if (std::regex_search(line, m_loss, loss_re)) {
            pt.loss = std::stod(m_loss[1].str());
            found = true;
        }
        if (std::regex_search(line, m_step, step_re)) {
            pt.step = std::stoi(m_step[1].str());
        } else {
            pt.step = data.size() + 1; // fallback
        }
        if (std::regex_search(line, m_lr, lr_re)) {
            pt.lr = std::stod(m_lr[1].str());
        }
        
        if (found) {
            data.push_back(pt);
        }
    }
    return data;
}

// Braille characters range: U+2800 to U+28FF
// Base is 0x2800. The bits are:
// 1 8
// 2 10
// 4 20
// 40 80
std::string get_braille(int pattern) {
    int code = 0x2800 + pattern;
    // UTF-8 encode
    std::string s;
    s += (char)(0xE0 | (code >> 12));
    s += (char)(0x80 | ((code >> 6) & 0x3F));
    s += (char)(0x80 | (code & 0x3F));
    return s;
}

void draw_graph(const std::vector<DataPoint>& data, int width, int height) {
    if (data.empty()) return;
    
    double min_loss = data[0].loss;
    double max_loss = data[0].loss;
    for (const auto& d : data) {
        if (d.loss < min_loss) min_loss = d.loss;
        if (d.loss > max_loss) max_loss = d.loss;
    }
    if (max_loss == min_loss) {
        max_loss += 0.1;
        min_loss -= 0.1;
    }

    int n = data.size();
    int graph_width = width * 2;
    int graph_height = height * 4;

    std::vector<std::vector<int>> grid(height, std::vector<int>(width, 0));

    for (int col = 0; col < graph_width; ++col) {
        int idx = (col * n) / graph_width;
        if (idx >= n) idx = n - 1;
        double val = data[idx].loss;
        int row = (int)(((val - min_loss) / (max_loss - min_loss)) * (graph_height - 1));
        if (row < 0) row = 0;
        if (row >= graph_height) row = graph_height - 1;

        // Invert Y axis
        row = (graph_height - 1) - row;

        int char_col = col / 2;
        int char_row = row / 4;
        int bit_col = col % 2;
        int bit_row = row % 4;

        int bit = 0;
        if (bit_col == 0) {
            if (bit_row == 0) bit = 1;
            else if (bit_row == 1) bit = 2;
            else if (bit_row == 2) bit = 4;
            else if (bit_row == 3) bit = 64;
        } else {
            if (bit_row == 0) bit = 8;
            else if (bit_row == 1) bit = 16;
            else if (bit_row == 2) bit = 32;
            else if (bit_row == 3) bit = 128;
        }
        if (char_row < height && char_col < width) {
            grid[char_row][char_col] |= bit;
        }
    }

    std::cout << COLOR_MED_GREEN;
    for (int r = 0; r < height; ++r) {
        for (int c = 0; c < width; ++c) {
            std::cout << get_braille(grid[r][c]);
        }
        std::cout << "\n";
    }
    std::cout << COLOR_RESET;
}

static PyObject* run_dashboard(PyObject* self, PyObject* args) {
    const char* log_path;
    if (!PyArg_ParseTuple(args, "s", &log_path)) {
        return NULL;
    }

    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);

    TermLock lock;
    lock.lock();

    std::cout << "\033[2J"; // Clear screen

    while (g_running) {
        std::cout << "\033[H"; // Move cursor to top-left
        
        std::vector<DataPoint> data = parse_log(log_path);
        
        std::cout << COLOR_BLACK_BG << COLOR_MED_GREEN;
        std::cout << "╔══════════════════════════════════════════════════════════════════════════════╗\n";
        std::cout << "║                          cctvtop - Training Monitor                          ║\n";
        std::cout << "╠══════════════════════════════════════════════════════════════════════════════╣\n";
        std::cout << COLOR_RESET;

        if (data.empty()) {
            std::cout << COLOR_DARK_GREEN << " Waiting for training data...\n" << COLOR_RESET;
        } else {
            DataPoint latest = data.back();
            
            // Simple exponential decay estimate for final/1h/1d loss
            double current_loss = latest.loss;
            double est_final = current_loss * 0.8;
            double est_1hr = current_loss * 0.95;
            double est_1d = current_loss * 0.85;

            std::cout << COLOR_DARK_GREEN 
                      << " Step: " << std::setw(6) << latest.step 
                      << " | Loss: " << std::fixed << std::setprecision(4) << current_loss
                      << " | LR: " << std::scientific << latest.lr << "\n" << COLOR_RESET;
                      
            std::cout << COLOR_DARK_GREEN
                      << " Est. Final Loss: " << std::fixed << std::setprecision(4) << est_final 
                      << " | 1-Hour Loss: " << est_1hr 
                      << " | 1-Day Loss: " << est_1d << "\n\n" << COLOR_RESET;

            std::cout << COLOR_MED_GREEN << " Loss Graph (Braille C++ engine)\n" << COLOR_RESET;
            std::cout << COLOR_DARK_GREEN << " Key: [y-axis: loss, x-axis: time]\n" << COLOR_RESET;

            draw_graph(data, 76, 10);
        }

        std::cout << "\n" << COLOR_DARK_GREEN << " Updating every 30 seconds... (Ctrl+C to quit)" << COLOR_RESET << "\n";
        
        // Sleep for 30 seconds, checking g_running periodically
        for (int i = 0; i < 300 && g_running; ++i) {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
    }

    lock.unlock();
    std::cout << std::flush;
    std::cout << "\n\033[0m\033[2J\033[H"; // Reset, clear screen, move to home
    Py_RETURN_NONE;
}

static PyMethodDef CCTVTopMethods[] = {
    {"run_dashboard", run_dashboard, METH_VARARGS, "Run the CCTVTop dashboard"},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef cctvtopmodule = {
    PyModuleDef_HEAD_INIT,
    "cctvtop_ext",
    "C++ CCTVTop Extension",
    -1,
    CCTVTopMethods
};

PyMODINIT_FUNC PyInit_cctvtop_ext(void) {
    return PyModule_Create(&cctvtopmodule);
}
