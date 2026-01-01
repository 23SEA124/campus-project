var InitialCount = -1;

const API_BASE = "https://lionfish-app-oy7gr.ondigitalocean.app";
function goFullScreen() {
    var el = document.documentElement;
    if (el.requestFullscreen) {
        el.requestFullscreen();
    } else if (el.webkitRequestFullscreen) {
        el.webkitRequestFullscreen();
    } else if (el.mozRequestFullScreen) {
        el.mozRequestFullScreen();
    }
}


/* =========================
   CLEAR PRODUCTS (CHECKOUT)
   ========================= */
const deleteProducts = async () => {
    try {
        await axios.delete(`${API_BASE}/product`, { withCredentials: false });
        console.log("Products cleared on server");
    } catch (err) {
        console.error("Failed to clear products:", err);
    }
};

/* =========================
   LOAD PRODUCTS
   ========================= */
const loadProducts = async () => {
    try {
        let res = await axios.get(`${API_BASE}/product`, { withCredentials: false });
        const products = res.data;
        const len = products.length;

        if (len === 0) {
            $("#home").empty();
            $("#1").css("display", "grid");
            $("#home").css("display", "none");
            $("#2").css("display", "none");
            InitialCount = -1;
            return;
        }

        if (len > InitialCount + 1) {
            $("#1").css("display", "none");
            $("#home").css("display", "grid");
            $("#2").css("display", "grid");

            let payable = 0;
            for (let product of products) {
                payable += parseFloat(product.payable);
            }

            const product = products[products.length - 1];

            const x = `
            <section>
                <div class="card card-long animated fadeInUp once">
                    <img src="asset/img/${product.id}.jpg" class="album">
                    <div class="span1">Product Name</div>
                    <div class="card__product">${product.name}</div>

                    <div class="span2">Per Unit</div>
                    <div class="card__price">${product.price}</div>

                    <div class="span3">Units</div>
                    <div class="card__unit">${product.taken} ${product.unit}</div>

                    <div class="span4">Payable</div>
                    <div class="card__amount">${product.payable}</div>
                </div>
            </section>
            `;

            document.getElementById("home").innerHTML += x;
            document.getElementById("2").innerHTML =
                "CHECKOUT LKR " + payable.toFixed(2);

            InitialCount += 1;
        }
    } catch (err) {
        console.error("Load products failed:", err);
    }
};

/* =========================
   CHECKOUT FUNCTION
   ========================= */
/* =========================
   CHECKOUT FUNCTION (FIXED)
   ========================= */
var checkout = async () => {
    try {
        document.getElementById("2").innerHTML =
            "<span class='loader-16' style='margin-left:44%;'></span>";

        let res = await axios.get(`${API_BASE}/product`, { withCredentials: false });
        const products = res.data;

        let payable = 0;
        for (let product of products) {
            payable += parseFloat(product.payable);
        }

        const plainData = `Total Payable: LKR ${payable.toFixed(2)}`;
        const qrUrl =
            `https://api.qrserver.com/v1/create-qr-code/?data=${encodeURIComponent(plainData)}&size=400x400&color=02c8db&bgcolor=ecf0f3`;

        const img = await fetch(qrUrl).then(r => r.blob());
        const image = URL.createObjectURL(img);

        $("#home").css("display", "none");
        $("#final").css("display", "none");
        $("#image").attr("src", image);
        $("#qr").css("display", "grid");

        setTimeout(async () => {
            $("#qr").css("display", "none");
            $("#success").css("display", "grid");

            // 1. Clear products on server
            await deleteProducts();

            // 2. WAIT AND RESET (NO RELOAD)
            setTimeout(() => {
                // Reset UI visibility
                $("#success").css("display", "none");
                $("#1").css("display", "grid"); // Show "Place Items" animation
                $("#home").css("display", "none").empty(); // Clear product list
                $("#2").css("display", "none").html("CHECKOUT"); // Reset button text
                $("#final").css("display", "block");

                // CRITICAL: Reset the counter so the loop starts from 0 again
                InitialCount = -1; 
                
            }, 3000); // 3 seconds of success screen before reset

        }, 10000);

    } catch (err) {
        console.error("Checkout failed:", err);
    }
};

/* =========================
   AUTO LOAD LOOP
   ========================= */
window.onload = () => {
    setInterval(loadProducts, 300);
};
