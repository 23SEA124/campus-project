const express = require("express");
const bodyParser = require("body-parser");
const cors = require("cors");
const path = require("path");

const app = express();
var port = process.env.PORT || 3000;

let products = [];
let orders = [];

app.use(cors());
app.use(bodyParser.urlencoded({ extended: false }));
app.use(bodyParser.json());

// Disable caching (important for mobile browsers)
app.use((req, res, next) => {
    res.setHeader("Cache-Control", "no-store, no-cache, must-revalidate, proxy-revalidate");
    res.setHeader("Pragma", "no-cache");
    res.setHeader("Expires", "0");
    next();
});

// Serve static files
app.use(express.static(path.join(__dirname)));

// Serve Checkout UI
app.get("/", (req, res) => {
    res.sendFile(path.join(__dirname, "index.html"));
});

// API routes
app.post("/product", (req, res) => {
    const product = req.body;
    console.log(product);
    products.push(product);
    res.send("Product added");
});

app.get("/product", (req, res) => {
    res.json(products);
});

app.post("/checkout", (req, res) => {
    const order = req.body;
    orders.push(order);
    res.send("Checkout successful");
});

app.listen(port, () => {
    console.log(`Server running on port ${port}`);
});

// Clear all products (checkout)
app.delete("/product", (req, res) => {
    products = [];
    res.json({ status: "all products cleared" });
});
