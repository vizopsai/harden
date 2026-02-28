"""
URL configuration for myapp project.
"""
from django.contrib import admin
from django.urls import path
from . import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.index, name='index'),
    path('api/products/', views.product_list, name='product_list'),
    path('api/products/<int:product_id>/', views.product_detail, name='product_detail'),
    path('api/products/create/', views.product_create, name='product_create'),
]
