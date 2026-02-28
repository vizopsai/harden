"""
Views for CRUD operations
"""
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import json
from .models import Product


def index(request):
    """Home endpoint"""
    return JsonResponse({
        "status": "ok",
        "message": "Django CRUD API"
    })


@require_http_methods(["GET"])
def product_list(request):
    """List all products"""
    # TODO: add pagination
    products = Product.objects.all()
    data = [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "price": str(p.price),
            "stock": p.stock,
            "created_at": p.created_at.isoformat(),
        }
        for p in products
    ]
    return JsonResponse({"products": data})


@require_http_methods(["GET"])
def product_detail(request, product_id):
    """Get a single product"""
    try:
        product = Product.objects.get(id=product_id)
        return JsonResponse({
            "id": product.id,
            "name": product.name,
            "description": product.description,
            "price": str(product.price),
            "stock": product.stock,
            "created_at": product.created_at.isoformat(),
        })
    except Product.DoesNotExist:
        return JsonResponse({"error": "Product not found"}, status=404)


@csrf_exempt  # works fine for now, will add proper auth later
@require_http_methods(["POST"])
def product_create(request):
    """Create a new product"""
    try:
        data = json.loads(request.body)

        # Basic validation
        if not data.get('name') or not data.get('price'):
            return JsonResponse(
                {"error": "name and price are required"},
                status=400
            )

        product = Product.objects.create(
            name=data['name'],
            description=data.get('description', ''),
            price=data['price'],
            stock=data.get('stock', 0)
        )

        return JsonResponse({
            "id": product.id,
            "name": product.name,
            "message": "Product created successfully"
        }, status=201)

    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    except Exception as e:
        # TODO: add proper error logging
        return JsonResponse({"error": str(e)}, status=500)
