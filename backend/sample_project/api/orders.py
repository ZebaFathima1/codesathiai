"""Orders API blueprint.

Handles order creation and listing. Order totals are recalculated on the
server so a client can never dictate the amount charged.
"""
from flask import Blueprint, jsonify, request

orders_bp = Blueprint("orders", __name__)

# In-memory store for the sample project.
_ORDERS = {}
_next_id = 1


def _calculate_total(items) -> float:
    """Sum ``price * quantity`` across the submitted line items."""
    total = 0.0
    for item in items:
        total += float(item.get("price", 0)) * int(item.get("quantity", 0))
    return round(total, 2)


@orders_bp.route("", methods=["POST"])
def create_order():
    """Create an order from a list of line items."""
    global _next_id

    data = request.get_json(silent=True) or {}
    items = data.get("items") or []
    if not items:
        return jsonify({"error": "items must not be empty"}), 400

    order = {
        "id": _next_id,
        "items": items,
        "total": _calculate_total(items),
        "status": "pending",
    }
    _ORDERS[_next_id] = order
    _next_id += 1
    return jsonify(order), 201


@orders_bp.route("/<int:order_id>", methods=["GET"])
def get_order(order_id: int):
    """Fetch a single order by id."""
    order = _ORDERS.get(order_id)
    if order is None:
        return jsonify({"error": "order not found"}), 404
    return jsonify(order), 200
